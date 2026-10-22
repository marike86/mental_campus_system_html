import csv
import io
import json
import re
import urllib.parse
import logging
from datetime import date, timedelta, datetime, timezone
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func as sql_func
from database import get_db
from models.user import User
from models.bootcamp import Bootcamp
from models.day_form import DayForm
from models.enrollment import Enrollment
from models.submission import Submission
from models.batch import Batch
from models.audit_log import AuditLog
from models.user_badge import UserBadge
from auth import require_admin, get_password_hash, verify_csrf
from config import APP_NAME
from templates_config import templates
from utils.crypto import decrypt_data
from services.clock import local_date
from services.versions import write_lock
from utils.sanitize import sanitize_text, sanitize_email, validate_password_strength
from routes.audit import log_admin_action

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])


@router.get("/admin/bootcamps")
async def admin_bootcamps(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        bootcamps = db.query(Bootcamp).order_by(Bootcamp.created_at.desc()).all()
        return templates.TemplateResponse("admin/bootcamps.html", {
            "request": request, "user": admin, "app_name": APP_NAME, "bootcamps": bootcamps,
        })
    except Exception as e:
        logger.exception("加载训练营列表失败 (admin_id=%d): %s", admin.id, e)
        raise HTTPException(status_code=500, detail="加载训练营列表时发生错误")


@router.get("/admin/bootcamp/new")
async def new_bootcamp_page(request: Request, admin: User = Depends(require_admin)):
    return templates.TemplateResponse("admin/form_editor.html", {
        "request": request, "user": admin, "app_name": APP_NAME, "bootcamp": None, "day": None, "day_form": None,
    })


@router.post("/admin/bootcamp/new")
async def create_bootcamp(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    form_data = await request.form()
    name = form_data.get("name", "").strip()
    description = form_data.get("description", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="训练营名称不能为空")
    try:
        days = int(form_data.get("days", 7))
    except (TypeError, ValueError):
        days = 7
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="天数必须在 1-365 之间")
    bootcamp = Bootcamp(name=name, description=description, days=days, created_by=admin.id)
    db.add(bootcamp)
    db.flush()
    for i in range(1, days + 1):
        day_form = DayForm(bootcamp_id=bootcamp.id, day_number=i, questions=[])
        db.add(day_form)
    db.commit()
    log_admin_action(db, admin.id, "创建训练营", "bootcamp", bootcamp.id, {"name": name})
    return RedirectResponse(f"/admin/bootcamp/{bootcamp.id}", status_code=302)


@router.get("/admin/bootcamp/{bootcamp_id}")
async def bootcamp_detail(request: Request, bootcamp_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    bootcamp = db.query(Bootcamp).filter(Bootcamp.id == bootcamp_id).first()
    if not bootcamp:
        raise HTTPException(status_code=404, detail="训练营不存在")
    day_forms = db.query(DayForm).filter(DayForm.bootcamp_id == bootcamp_id).order_by(DayForm.day_number).all()
    return templates.TemplateResponse("admin/form_editor.html", {
        "request": request, "user": admin, "app_name": APP_NAME, "bootcamp": bootcamp, "day_forms": day_forms,
        "day": None, "questions_json": None,
    })


@router.post("/admin/bootcamp/{bootcamp_id}")
async def update_bootcamp(request: Request, bootcamp_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    bootcamp = db.query(Bootcamp).filter(Bootcamp.id == bootcamp_id).first()
    if not bootcamp:
        raise HTTPException(status_code=404, detail="训练营不存在")
    form_data = await request.form()
    new_name = form_data.get("name", "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="训练营名称不能为空")
    requested_days = form_data.get('days')
    if requested_days:
        try:
            days = int(requested_days)
        except ValueError:
            raise HTTPException(400, "天数必须为整数")
        if not 1 <= days <= 365:
            raise HTTPException(400, "天数必须在 1-365 之间")
        from models.workflow import EnrollmentDay
        started = db.query(EnrollmentDay).join(Enrollment, Enrollment.id==EnrollmentDay.enrollment_id).filter(Enrollment.bootcamp_id==bootcamp.id).first()
        if days < bootcamp.days and started:
            raise HTTPException(409, "已有学员开始学习，不能缩短训练营")
        for day in range(bootcamp.days+1, days+1):
            db.add(DayForm(bootcamp_id=bootcamp.id, day_number=day, questions=[]))
        bootcamp.days = days
    bootcamp.name = new_name
    bootcamp.description = form_data.get("description", bootcamp.description).strip()
    db.commit()
    log_admin_action(db, admin.id, "更新训练营", "bootcamp", bootcamp.id, {"name": bootcamp.name})
    return RedirectResponse(f"/admin/bootcamp/{bootcamp_id}", status_code=302)


@router.get("/admin/bootcamp/{bootcamp_id}/day/{day}")
async def edit_day_form(request: Request, bootcamp_id: int, day: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    bootcamp = db.query(Bootcamp).filter(Bootcamp.id == bootcamp_id).first()
    if not bootcamp:
        raise HTTPException(status_code=404, detail="训练营不存在")
    day_form = db.query(DayForm).filter(DayForm.bootcamp_id == bootcamp_id, DayForm.day_number == day).first()
    if not day_form:
        raise HTTPException(status_code=404, detail="表单不存在")
    questions_json = json.dumps(day_form.questions, ensure_ascii=False) if day_form.questions else "[]"
    return templates.TemplateResponse("admin/form_editor.html", {
        "request": request, "user": admin, "app_name": APP_NAME,
        "bootcamp": bootcamp, "day_form": day_form, "day": day, "questions_json": questions_json,
    })


@router.post("/admin/bootcamp/{bootcamp_id}/day/{day}")
async def save_day_form(request: Request, bootcamp_id: int, day: int, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    day_form = db.query(DayForm).filter(DayForm.bootcamp_id == bootcamp_id, DayForm.day_number == day).first()
    if not day_form:
        raise HTTPException(status_code=404, detail="表单不存在")
    form_data = await request.form()
    questions_str = form_data.get("questions", "[]")
    try:
        questions = json.loads(questions_str)
    except json.JSONDecodeError:
        raise HTTPException(400, "题目 JSON 格式错误")
    if not isinstance(questions, list):
        raise HTTPException(400, "题目必须为列表")
    day_form.questions = questions
    db.commit()
    return RedirectResponse(f"/admin/bootcamp/{bootcamp_id}", status_code=302)


@router.post("/admin/bootcamp/{bootcamp_id}/toggle")
async def toggle_bootcamp(bootcamp_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    bootcamp = db.query(Bootcamp).filter(Bootcamp.id == bootcamp_id).first()
    if not bootcamp:
        raise HTTPException(status_code=404, detail="训练营不存在")
    bootcamp.is_active = not bootcamp.is_active
    db.commit()
    action = "发布训练营" if bootcamp.is_active else "下线训练营"
    log_admin_action(db, admin.id, action, "bootcamp", bootcamp.id)
    return RedirectResponse("/admin/bootcamps", status_code=302)


@router.get("/admin/users")
async def admin_users(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).filter(User.role == "user").order_by(User.created_at.desc()).all()
    bootcamps = db.query(Bootcamp).filter(Bootcamp.is_active == True).all()
    enrollments = db.query(Enrollment).all()
    enrollment_map = {}
    for e in enrollments:
        if e.user_id not in enrollment_map:
            enrollment_map[e.user_id] = []
        enrollment_map[e.user_id].append(e.bootcamp_id)
    bootcamp_batches = {}
    for b in bootcamps:
        batches = db.query(Batch).filter(Batch.bootcamp_id == b.id, Batch.is_active == True).all()
        bootcamp_batches[b.id] = [{"id": bat.id, "name": bat.name} for bat in batches]
    return templates.TemplateResponse("admin/users.html", {
        "request": request, "user": admin, "app_name": APP_NAME,
        "users": users, "bootcamps": bootcamps, "enrollment_map": enrollment_map,
        "bootcamp_batches": bootcamp_batches,
    })


@router.post("/admin/enroll")
async def enroll_user(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    form_data = await request.form()
    user_id_str = form_data.get("user_id", "")
    bootcamp_id_str = form_data.get("bootcamp_id", "")
    if not user_id_str or not bootcamp_id_str:
        raise HTTPException(status_code=400, detail="用户ID和训练营ID不能为空")
    try:
        user_id = int(user_id_str)
        bootcamp_id = int(bootcamp_id_str)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="用户ID和训练营ID必须为数字")
    existing = db.query(Enrollment).filter(Enrollment.user_id == user_id, Enrollment.bootcamp_id == bootcamp_id).first()
    if not existing:
        batch_id = form_data.get("batch_id", "").strip()
        enrollment = Enrollment(
            user_id=user_id,
            bootcamp_id=bootcamp_id,
            start_date=enrollment_start(db, bootcamp_id, int(batch_id) if batch_id and batch_id.isdigit() else None),
            batch_id=int(batch_id) if batch_id and batch_id.isdigit() else None
        )
        db.add(enrollment)
        db.commit()
        log_admin_action(db, admin.id, "分配训练营", "enrollment", enrollment.id, {"user_id": user_id, "bootcamp_id": bootcamp_id})
    return RedirectResponse("/admin/users", status_code=302)


@router.get("/admin/export")
async def export_page(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    bootcamps = db.query(Bootcamp).all()
    bootcamp_data = []
    for b in bootcamps:
        batches = db.query(Batch).filter(Batch.bootcamp_id == b.id).order_by(Batch.created_at.desc()).all()
        bootcamp_data.append({"id": b.id, "name": b.name, "days": b.days, "batch_list": [{"id": bat.id, "name": bat.name} for bat in batches]})
    return templates.TemplateResponse("admin/export.html", {
        "request": request, "user": admin, "app_name": APP_NAME, "bootcamps": bootcamp_data, "data": None, "selected_bootcamp": None,
    })


@router.post("/admin/export")
async def export_csv(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    try:
        form_data = await request.form()
        bootcamp_id_str = form_data.get("bootcamp_id", "")
        if not bootcamp_id_str:
            raise HTTPException(status_code=400, detail="请选择训练营")
        try:
            bootcamp_id = int(bootcamp_id_str)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="训练营ID必须为数字")
        batch_id = form_data.get("batch_id", "").strip()
        bootcamp = db.query(Bootcamp).filter(Bootcamp.id == bootcamp_id).first()
        if not bootcamp:
            raise HTTPException(status_code=404, detail="训练营不存在")
        enrollment_query = db.query(Enrollment).filter(Enrollment.bootcamp_id == bootcamp_id)
        if batch_id:
            try:
                batch_id_int = int(batch_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="批次ID必须为数字")
            enrollment_query = enrollment_query.filter(Enrollment.batch_id == batch_id_int)
        enrollments = enrollment_query.all()
        day_forms = {}
        for df in db.query(DayForm).filter(DayForm.bootcamp_id == bootcamp_id).all():
            day_forms[df.day_number] = df
        output = io.StringIO()
        output.write('\ufeff')
        writer = csv.writer(output)
        writer.writerow(["用户昵称", "日期", "天数", "题目", "答案", "版本号", "提交轮次", "实际提交时间", "审核状态"])
        for e in enrollments:
            user = db.query(User).filter(User.id == e.user_id).first()
            if not user:
                continue
            submissions = db.query(Submission).filter(Submission.enrollment_id == e.id).order_by(Submission.day_number).all()
            from models.workflow import SubmissionAttempt, DayFormVersion
            for s in submissions:
                attempts = db.query(SubmissionAttempt).filter_by(submission_id=s.id).order_by(SubmissionAttempt.round_number).all()
                for attempt in attempts:
                    version = db.get(DayFormVersion, attempt.version_id)
                    answers = decrypt_data(attempt.answers)
                    for q in version.questions:
                        answer = answers.get(q["id"], "")
                        if isinstance(answer, list):
                            answer = ", ".join(answer)
                        submit_date = e.start_date + timedelta(days=s.day_number-1) if e.start_date else ""
                        cells = [user.nickname, str(submit_date), s.day_number, q.get("label", ""), answer,
                                 version.version, attempt.round_number, attempt.submitted_at.isoformat(), attempt.review_status]
                        writer.writerow([("'"+str(c)) if str(c).startswith(("=", "+", "-", "@")) else c for c in cells])
        output.seek(0)
        safe_name = re.sub(r'[^\w\u4e00-\u9fff-]', '_', bootcamp.name)
        filename = f"{safe_name}_export.csv"
        encoded_filename = urllib.parse.quote(filename)
        log_admin_action(db, admin.id, "导出数据", "bootcamp", bootcamp_id, {"batch_id": batch_id, "enrollment_count": len(enrollments)})
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode("utf-8-sig")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("CSV导出失败 (admin_id=%d): %s", admin.id, e)
        bootcamps = db.query(Bootcamp).all()
        bootcamp_data = [{"id": b.id, "name": b.name, "days": b.days, "batch_list": []} for b in bootcamps]
        return templates.TemplateResponse("admin/export.html", {
            "request": request, "user": admin, "app_name": APP_NAME,
            "bootcamps": bootcamp_data, "data": None, "selected_bootcamp": None,
            "error": "导出失败，请稍后重试",
        }, status_code=500)


@router.get("/admin/dashboard")
async def admin_dashboard(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    total_users = db.query(User).filter(User.role == "user").count()
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    active_users = db.query(User).filter(User.role == "user", User.last_login >= week_ago).count()
    total_bootcamps = db.query(Bootcamp).count()
    total_submissions = db.query(Submission).count()
    bootcamp_stats = []
    all_bootcamps = db.query(Bootcamp).order_by(Bootcamp.created_at.desc()).all()
    
    enrollment_counts = dict(
        db.query(Enrollment.bootcamp_id, sql_func.count(Enrollment.id))
        .group_by(Enrollment.bootcamp_id).all()
    )
    
    for b in all_bootcamps:
        enrolled = enrollment_counts.get(b.id, 0)
        completed_count = 0
        if enrolled > 0:
            enrollments = db.query(Enrollment).filter(Enrollment.bootcamp_id == b.id).all()
            enrollment_ids = [e.id for e in enrollments]
            submission_counts = dict(
                db.query(Submission.enrollment_id, sql_func.count(Submission.id))
                .filter(Submission.enrollment_id.in_(enrollment_ids))
                .group_by(Submission.enrollment_id).all()
            )
            completed_count = sum(1 for count in submission_counts.values() if count >= b.days)
        rate = int((completed_count / enrolled * 100)) if enrolled > 0 else 0
        bootcamp_stats.append({"name": b.name, "enrolled": enrolled, "completion_rate": rate})
    bootcamp_stats.sort(key=lambda x: x["completion_rate"], reverse=True)
    likert_stats = _collect_likert_stats(db)
    log_admin_action(db, admin.id, "查看数据看板", "dashboard")
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request, "user": admin, "app_name": APP_NAME,
        "total_users": total_users, "active_users": active_users,
        "total_bootcamps": total_bootcamps, "total_submissions": total_submissions,
        "bootcamp_stats": bootcamp_stats, "likert_stats": likert_stats,
    })


def _collect_likert_stats(db: Session):
    all_day_forms = db.query(DayForm).all()
    likert_questions = {}
    for df in all_day_forms:
        for q in (df.questions or []):
            if q.get("type") == "likert":
                key = f"{df.bootcamp_id}_{q['id']}"
                if key not in likert_questions:
                    likert_questions[key] = {
                        "qid": q["id"], "label": q["label"],
                        "labels": q.get("labels", []),
                        "min": q.get("min", 1), "max": q.get("max", 5),
                        "bootcamp_id": df.bootcamp_id, "day_number": df.day_number
                    }
    results = []
    if not likert_questions:
        return results
    
    all_submissions = db.query(Submission).all()
    
    for key, qinfo in list(likert_questions.items())[:5]:
        counts = {}
        for i in range(qinfo["min"], qinfo["max"] + 1):
            counts[i] = 0
        for s in all_submissions:
            answers = decrypt_data(s.answers) if isinstance(s.answers, str) else s.answers
            val = answers.get(qinfo["qid"], None)
            if isinstance(val, int) and val in counts:
                counts[val] += 1
        total_answers = sum(counts.values())
        if total_answers == 0:
            continue
        options = []
        for i in range(qinfo["min"], qinfo["max"] + 1):
            label = qinfo["labels"][i - qinfo["min"]] if qinfo["labels"] and i - qinfo["min"] < len(qinfo["labels"]) else str(i)
            count = counts[i]
            pct = int((count / total_answers * 100)) if total_answers > 0 else 0
            options.append({"label": label, "count": count, "pct": pct})
        results.append({"question_label": qinfo["label"], "options": options})
    return results


@router.get("/admin/batches")
async def admin_batches(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    bootcamps = db.query(Bootcamp).order_by(Bootcamp.created_at.desc()).all()
    bootcamp_list = []
    for b in bootcamps:
        batches = db.query(Batch).filter(Batch.bootcamp_id == b.id).order_by(Batch.created_at.desc()).all()
        batch_data = []
        for batch in batches:
            user_count = db.query(Enrollment).filter(Enrollment.batch_id == batch.id).count()
            batch_data.append({
                "id": batch.id,
                "name": batch.name,
                "description": batch.description,
                "start_date": batch.start_date,
                "end_date": batch.end_date,
                "is_active": batch.is_active,
                "created_at": batch.created_at,
                "user_count": user_count
            })
        bootcamp_list.append({"id": b.id, "name": b.name, "days": b.days, "batches": batch_data})
    return templates.TemplateResponse("admin/batches.html", {
        "request": request, "user": admin, "app_name": APP_NAME, "bootcamps": bootcamp_list,
    })


@router.post("/admin/batch/new")
async def create_batch(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    form_data = await request.form()
    bootcamp_id_str = form_data.get("bootcamp_id", "")
    if not bootcamp_id_str:
        raise HTTPException(status_code=400, detail="请选择训练营")
    try:
        bootcamp_id = int(bootcamp_id_str)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="训练营ID必须为数字")
    name = form_data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="批次名称不能为空")
    start_date_str = form_data.get("start_date", "").strip()
    end_date_str = form_data.get("end_date", "").strip()
    start_date = None
    end_date = None
    if start_date_str:
        try:
            start_date = date.fromisoformat(start_date_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="开始日期格式不正确")
    if end_date_str:
        try:
            end_date = date.fromisoformat(end_date_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="结束日期格式不正确")
    batch = Batch(
        bootcamp_id=bootcamp_id,
        name=name,
        start_date=start_date,
        end_date=end_date,
    )
    db.add(batch)
    db.commit()
    log_admin_action(db, admin.id, "创建批次", "batch", batch.id, {"name": name, "bootcamp_id": bootcamp_id})
    return RedirectResponse("/admin/batches", status_code=302)


@router.post("/admin/view-user-data")
async def view_user_data(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    form_data = await request.form()
    user_id_str = form_data.get("user_id", "")
    if not user_id_str:
        raise HTTPException(status_code=400, detail="用户ID不能为空")
    try:
        user_id = int(user_id_str)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="用户ID必须为数字")
    log_admin_action(db, admin.id, "查看用户数据", "user", user_id)
    return RedirectResponse(f"/admin/users", status_code=302)


@router.post("/admin/batch-enroll")
async def batch_enroll_users(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    try:
        form_data = await request.form()
        bootcamp_id_str = form_data.get("bootcamp_id", "")
        user_ids_str = form_data.get("user_ids", "")
        if not bootcamp_id_str:
            raise HTTPException(status_code=400, detail="请选择训练营")
        try:
            bootcamp_id = int(bootcamp_id_str)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="训练营ID必须为数字")
        bootcamp = db.query(Bootcamp).filter(Bootcamp.id == bootcamp_id).first()
        if not bootcamp:
            raise HTTPException(status_code=404, detail="训练营不存在")
        if not user_ids_str:
            raise HTTPException(status_code=400, detail="请选择要分配的用户")
        user_id_list = []
        for uid_str in user_ids_str.split(","):
            uid_str = uid_str.strip()
            if uid_str:
                try:
                    user_id_list.append(int(uid_str))
                except (TypeError, ValueError):
                    continue
        if not user_id_list:
            raise HTTPException(status_code=400, detail="没有有效的用户ID")
        batch_id_str = form_data.get("batch_id", "").strip()
        batch_id = int(batch_id_str) if batch_id_str and batch_id_str.isdigit() else None
        enrolled_count = 0
        skipped_count = 0
        for uid in user_id_list:
            existing = db.query(Enrollment).filter(
                Enrollment.user_id == uid, Enrollment.bootcamp_id == bootcamp_id
            ).first()
            if existing:
                skipped_count += 1
                continue
            user = db.query(User).filter(User.id == uid).first()
            if not user:
                skipped_count += 1
                continue
            enrollment = Enrollment(
                user_id=uid,
                bootcamp_id=bootcamp_id,
                start_date=enrollment_start(db, bootcamp_id, batch_id),
                batch_id=batch_id,
            )
            db.add(enrollment)
            enrolled_count += 1
        db.commit()
        log_admin_action(db, admin.id, "批量分配训练营", "bootcamp", bootcamp_id, {
            "user_ids": user_id_list, "batch_id": batch_id,
            "enrolled": enrolled_count, "skipped": skipped_count,
        })
        return RedirectResponse("/admin/users", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("批量分配训练营失败 (admin_id=%d): %s", admin.id, e)
        raise HTTPException(status_code=500, detail="批量分配训练营时发生错误")


@router.post("/admin/reset-password")
async def admin_reset_password(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    try:
        form_data = await request.form()
        user_id_str = form_data.get("user_id", "")
        new_password = form_data.get("new_password", "")
        if not user_id_str:
            raise HTTPException(status_code=400, detail="用户ID不能为空")
        try:
            user_id = int(user_id_str)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="用户ID必须为数字")
        if not new_password or len(new_password) < 6:
            raise HTTPException(status_code=400, detail="新密码长度不能少于6位")
        pwd_valid, pwd_error = validate_password_strength(new_password)
        if not pwd_valid:
            raise HTTPException(status_code=400, detail=pwd_error)
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        user.hashed_password = get_password_hash(new_password)
        db.commit()
        log_admin_action(db, admin.id, "重置用户密码", "user", user_id)
        return RedirectResponse("/admin/users", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("重置密码失败 (admin_id=%d): %s", admin.id, e)
        raise HTTPException(status_code=500, detail="重置密码时发生错误")


@router.post("/admin/delete-user")
async def admin_delete_user(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    try:
        form_data = await request.form()
        user_id_str = form_data.get("user_id", "")
        confirm = form_data.get("confirm", "")
        if not user_id_str:
            raise HTTPException(status_code=400, detail="用户ID不能为空")
        try:
            user_id = int(user_id_str)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="用户ID必须为数字")
        if confirm != "yes":
            raise HTTPException(status_code=400, detail="请确认删除操作")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        if user.role == "admin":
            raise HTTPException(status_code=400, detail="不能删除管理员账号")
        user_nickname = user.nickname
        user_email = user.email
        enrollments = db.query(Enrollment).filter(Enrollment.user_id == user_id).all()
        enrollment_ids = [e.id for e in enrollments]
        if enrollment_ids:
            db.query(Submission).filter(Submission.enrollment_id.in_(enrollment_ids)).delete(synchronize_session=False)
            db.query(Enrollment).filter(Enrollment.user_id == user_id).delete(synchronize_session=False)
        db.query(UserBadge).filter(UserBadge.user_id == user_id).delete(synchronize_session=False)
        db.delete(user)
        db.commit()
        log_admin_action(db, admin.id, "删除用户", "user", user_id, {"nickname": user_nickname, "email": user_email})
        return RedirectResponse("/admin/users", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("删除用户失败 (admin_id=%d): %s", admin.id, e)
        raise HTTPException(status_code=500, detail="删除用户时发生错误")


@router.post("/admin/create-user")
async def admin_create_user(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    try:
        form_data = await request.form()
        email = form_data.get("email", "").strip()
        nickname = form_data.get("nickname", "").strip()
        password = form_data.get("password", "")
        role = form_data.get("role", "user")
        college = form_data.get("college", "").strip()
        student_id = form_data.get("student_id", "").strip()
        grade = form_data.get("grade", "").strip()
        email = sanitize_email(email)
        if not email:
            raise HTTPException(status_code=400, detail="邮箱格式不正确")
        nickname = sanitize_text(nickname)
        college = sanitize_text(college)
        student_id = sanitize_text(student_id)
        grade = sanitize_text(grade)
        pwd_valid, pwd_error = validate_password_strength(password)
        if not pwd_valid:
            raise HTTPException(status_code=400, detail=pwd_error)
        if not email:
            raise HTTPException(status_code=400, detail="邮箱不能为空")
        if not nickname:
            raise HTTPException(status_code=400, detail="昵称不能为空")
        if not password or len(password) < 6:
            raise HTTPException(status_code=400, detail="密码长度不能少于6位")
        # 权限控制：只有超级管理员可以创建admin角色
        if admin.role == "super_admin":
            allowed_roles = ("user", "admin", "reviewer")
        else:
            allowed_roles = ("user", "reviewer")
        if role not in allowed_roles:
            raise HTTPException(status_code=403, detail="无权创建该角色的用户")
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            raise HTTPException(status_code=400, detail="该邮箱已被注册")
        user = User(
            email=email,
            nickname=nickname,
            hashed_password=get_password_hash(password),
            role=role,
            college=college or None,
            student_id=student_id or None,
            grade=grade or None,
        )
        db.add(user)
        db.commit()
        log_admin_action(db, admin.id, "创建用户", "user", user.id, {"email": email, "nickname": nickname, "role": role})
        return RedirectResponse("/admin/users", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("创建用户失败 (admin_id=%d): %s", admin.id, e)
        raise HTTPException(status_code=500, detail="创建用户时发生错误")


@router.post("/admin/enrollment/{enrollment_id}/approve")
async def approve_enrollment(enrollment_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    try:
        enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
        if not enrollment:
            raise HTTPException(status_code=404, detail="申请不存在")
        enrollment.status = "approved"
        enrollment.start_date = enrollment.start_date or enrollment_start(db, enrollment.bootcamp_id, enrollment.batch_id)
        db.commit()
        log_admin_action(db, admin.id, "审批通过加入申请", "enrollment", enrollment_id)
        return RedirectResponse("/admin/users", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("审批加入申请失败 (admin_id=%d): %s", admin.id, e)
        raise HTTPException(status_code=500, detail="审批时发生错误")


@router.post("/admin/enrollment/{enrollment_id}/reject")
async def reject_enrollment(enrollment_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    try:
        enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
        if not enrollment:
            raise HTTPException(status_code=404, detail="申请不存在")
        enrollment.status = "rejected"
        db.commit()
        log_admin_action(db, admin.id, "拒绝加入申请", "enrollment", enrollment_id)
        return RedirectResponse("/admin/users", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("拒绝加入申请失败 (admin_id=%d): %s", admin.id, e)
        raise HTTPException(status_code=500, detail="操作失败")


@router.post("/admin/edit-user")
async def admin_edit_user(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    try:
        form_data = await request.form()
        user_id_str = form_data.get("user_id", "")
        if not user_id_str:
            raise HTTPException(status_code=400, detail="用户ID不能为空")
        try:
            user_id = int(user_id_str)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="用户ID必须为数字")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        nickname = form_data.get("nickname", "").strip()
        nickname = sanitize_text(nickname)
        if not nickname:
            raise HTTPException(status_code=400, detail="昵称不能为空")
        user.nickname = nickname
        student_id = sanitize_text(form_data.get("student_id", "").strip())
        college = sanitize_text(form_data.get("college", "").strip())
        grade = sanitize_text(form_data.get("grade", "").strip())
        user.student_id = student_id or None
        user.college = college or None
        user.grade = grade or None
        db.commit()
        log_admin_action(db, admin.id, "编辑用户信息", "user", user_id, {"nickname": nickname})
        return RedirectResponse("/admin/users", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("编辑用户失败 (admin_id=%d): %s", admin.id, e)
        raise HTTPException(status_code=500, detail="编辑用户信息时发生错误")


@router.post("/admin/batch/edit")
async def admin_edit_batch(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    try:
        form_data = await request.form()
        batch_id_str = form_data.get("batch_id", "")
        if not batch_id_str:
            raise HTTPException(status_code=400, detail="批次ID不能为空")
        try:
            batch_id = int(batch_id_str)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="批次ID必须为数字")
        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="批次不存在")
        name = form_data.get("name", "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="批次名称不能为空")
        batch.name = name
        batch.description = form_data.get("description", "").strip()
        start_date_str = form_data.get("start_date", "").strip()
        end_date_str = form_data.get("end_date", "").strip()
        if start_date_str:
            try:
                batch.start_date = date.fromisoformat(start_date_str)
            except ValueError:
                raise HTTPException(status_code=400, detail="开始日期格式不正确")
        else:
            batch.start_date = None
        if end_date_str:
            try:
                batch.end_date = date.fromisoformat(end_date_str)
            except ValueError:
                raise HTTPException(status_code=400, detail="结束日期格式不正确")
        else:
            batch.end_date = None
        is_active_str = form_data.get("is_active", "")
        batch.is_active = is_active_str in ("on", "true", "1")
        db.commit()
        log_admin_action(db, admin.id, "编辑批次", "batch", batch_id, {"name": name})
        return RedirectResponse("/admin/batches", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("编辑批次失败 (admin_id=%d): %s", admin.id, e)
        raise HTTPException(status_code=500, detail="编辑批次时发生错误")


@router.post("/admin/batch/delete")
async def admin_delete_batch(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    try:
        form_data = await request.form()
        batch_id_str = form_data.get("batch_id", "")
        if not batch_id_str:
            raise HTTPException(status_code=400, detail="批次ID不能为空")
        try:
            batch_id = int(batch_id_str)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="批次ID必须为数字")
        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="批次不存在")
        enrollment_count = db.query(Enrollment).filter(Enrollment.batch_id == batch_id).count()
        if enrollment_count > 0:
            db.query(Enrollment).filter(Enrollment.batch_id == batch_id).update(
                {"batch_id": None}, synchronize_session=False
            )
        batch_name = batch.name
        db.delete(batch)
        db.commit()
        log_admin_action(db, admin.id, "删除批次", "batch", batch_id, {
            "name": batch_name, "reassigned_enrollments": enrollment_count,
        })
        return RedirectResponse("/admin/batches", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("删除批次失败 (admin_id=%d): %s", admin.id, e)
        raise HTTPException(status_code=500, detail="删除批次时发生错误")


@router.post("/admin/batch/batch-delete")
async def admin_batch_delete_batches(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    try:
        form_data = await request.form()
        batch_ids_str = form_data.get("batch_ids", "")
        if not batch_ids_str:
            raise HTTPException(status_code=400, detail="请选择要删除的批次")
        batch_id_list = []
        for bid_str in batch_ids_str.split(","):
            bid_str = bid_str.strip()
            if bid_str:
                try:
                    batch_id_list.append(int(bid_str))
                except (TypeError, ValueError):
                    continue
        if not batch_id_list:
            raise HTTPException(status_code=400, detail="没有有效的批次ID")
        deleted_count = 0
        reassigned_total = 0
        for bid in batch_id_list:
            batch = db.query(Batch).filter(Batch.id == bid).first()
            if not batch:
                continue
            enrollment_count = db.query(Enrollment).filter(Enrollment.batch_id == bid).count()
            if enrollment_count > 0:
                db.query(Enrollment).filter(Enrollment.batch_id == bid).update(
                    {"batch_id": None}, synchronize_session=False
                )
                reassigned_total += enrollment_count
            db.delete(batch)
            deleted_count += 1
        db.commit()
        log_admin_action(db, admin.id, "批量删除批次", "batch", None, {
            "batch_ids": batch_id_list, "deleted": deleted_count, "reassigned_enrollments": reassigned_total,
        })
        return RedirectResponse("/admin/batches", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("批量删除批次失败 (admin_id=%d): %s", admin.id, e)
        raise HTTPException(status_code=500, detail="批量删除批次时发生错误")


def enrollment_start(db, camp_id, batch_id):
    if batch_id:
        batch = db.query(Batch).filter_by(id=batch_id, bootcamp_id=camp_id).first()
        if not batch:
            raise HTTPException(400, "批次不属于此训练营")
        return batch.start_date or local_date()
    return local_date()
