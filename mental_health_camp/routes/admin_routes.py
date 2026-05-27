import csv
import io
import json
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
from auth import require_admin
from config import APP_NAME
from templates_config import templates
from utils.crypto import decrypt_data
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
async def create_bootcamp(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
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
async def update_bootcamp(request: Request, bootcamp_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    bootcamp = db.query(Bootcamp).filter(Bootcamp.id == bootcamp_id).first()
    if not bootcamp:
        raise HTTPException(status_code=404, detail="训练营不存在")
    form_data = await request.form()
    new_name = form_data.get("name", "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="训练营名称不能为空")
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
async def save_day_form(request: Request, bootcamp_id: int, day: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    day_form = db.query(DayForm).filter(DayForm.bootcamp_id == bootcamp_id, DayForm.day_number == day).first()
    if not day_form:
        raise HTTPException(status_code=404, detail="表单不存在")
    form_data = await request.form()
    questions_str = form_data.get("questions", "[]")
    try:
        questions = json.loads(questions_str)
    except json.JSONDecodeError:
        questions = []
    day_form.questions = questions
    db.commit()
    return RedirectResponse(f"/admin/bootcamp/{bootcamp_id}", status_code=302)


@router.post("/admin/bootcamp/{bootcamp_id}/toggle")
async def toggle_bootcamp(bootcamp_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
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
async def enroll_user(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
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
            start_date=date.today(),
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
async def export_csv(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    form_data = await request.form()
    bootcamp_id_str = form_data.get("bootcamp_id", "")
    if not bootcamp_id_str:
        raise HTTPException(status_code=400, detail="请选择训练营")
    try:
        bootcamp_id = int(bootcamp_id_str)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="训练营ID必须为数字")
    batch_id = form_data.get("batch_id")
    bootcamp = db.query(Bootcamp).filter(Bootcamp.id == bootcamp_id).first()
    if not bootcamp:
        raise HTTPException(status_code=404, detail="训练营不存在")
    enrollment_query = db.query(Enrollment).filter(Enrollment.bootcamp_id == bootcamp_id)
    if batch_id:
        enrollment_query = enrollment_query.filter(Enrollment.batch_id == int(batch_id))
    enrollments = enrollment_query.all()
    day_forms = {}
    for df in db.query(DayForm).filter(DayForm.bootcamp_id == bootcamp_id).all():
        day_forms[df.day_number] = df
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(["用户昵称", "日期", "天数", "题目", "答案"])
    for e in enrollments:
        user = db.query(User).filter(User.id == e.user_id).first()
        if not user:
            continue
        submissions = db.query(Submission).filter(Submission.enrollment_id == e.id).order_by(Submission.day_number).all()
        for s in submissions:
            df = day_forms.get(s.day_number)
            if not df:
                continue
            answers = decrypt_data(s.answers) if isinstance(s.answers, str) else s.answers
            for q in df.questions:
                qid = q["id"]
                answer = answers.get(qid, "")
                if isinstance(answer, list):
                    answer = ", ".join(answer)
                elif q["type"] == "likert" and isinstance(answer, int):
                    labels = q.get("labels", [])
                    if 1 <= answer <= len(labels):
                        answer = f"{answer} - {labels[answer - 1]}"
                    else:
                        answer = str(answer)
                submit_date = e.start_date + timedelta(days=s.day_number - 1) if e.start_date else ""
                writer.writerow([user.nickname, str(submit_date), s.day_number, q.get("label", ""), answer])
    output.seek(0)
    filename = f"{bootcamp.name}_export.csv"
    log_admin_action(db, admin.id, "导出数据", "bootcamp", bootcamp_id, {"batch_id": batch_id, "enrollment_count": len(enrollments)})
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


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
        bootcamp_list.append({"bootcamp": b, "batches": batch_data})
    return templates.TemplateResponse("admin/batches.html", {
        "request": request, "user": admin, "app_name": APP_NAME, "bootcamps": bootcamp_list,
    })


@router.post("/admin/batch/new")
async def create_batch(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
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
    start_date_str = form_data.get("start_date")
    end_date_str = form_data.get("end_date")
    batch = Batch(
        bootcamp_id=bootcamp_id,
        name=name,
        start_date=date.fromisoformat(start_date_str) if start_date_str else None,
        end_date=date.fromisoformat(end_date_str) if end_date_str else None,
    )
    db.add(batch)
    db.commit()
    log_admin_action(db, admin.id, "创建批次", "batch", batch.id, {"name": name, "bootcamp_id": bootcamp_id})
    return RedirectResponse("/admin/batches", status_code=302)


@router.post("/admin/view-user-data")
async def view_user_data(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
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
