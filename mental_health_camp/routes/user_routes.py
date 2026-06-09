from datetime import date, timedelta
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func as sql_func
from database import get_db
from models.user import User
from models.bootcamp import Bootcamp
from models.day_form import DayForm
from models.enrollment import Enrollment
from models.submission import Submission
from models.badge import Badge
from models.user_badge import UserBadge
from auth import get_current_user, get_password_hash, verify_password, verify_csrf
from config import APP_NAME
from templates_config import templates
from utils.crypto import encrypt_data, decrypt_data
from utils.sanitize import sanitize_text, validate_password_strength

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user", tags=["user"])


@router.get("/dashboard")
async def user_dashboard(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enrollments = db.query(Enrollment).filter(Enrollment.user_id == current_user.id).all()
    bootcamp_data = []
    for e in enrollments:
        bootcamp = db.query(Bootcamp).filter(Bootcamp.id == e.bootcamp_id).first()
        if not bootcamp:
            continue
        completed = db.query(Submission).filter(Submission.enrollment_id == e.id).count()
        percentage = int((completed / bootcamp.days * 100)) if bootcamp.days > 0 else 0
        bootcamp_data.append({"enrollment": e, "bootcamp": bootcamp, "percentage": percentage, "completed": completed})
    return templates.TemplateResponse("user/dashboard.html", {
        "request": request, "user": current_user, "app_name": APP_NAME, "bootcamp_data": bootcamp_data,
    })


@router.get("/today")
async def today_tasks(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today = date.today()
    enrollments = db.query(Enrollment).filter(Enrollment.user_id == current_user.id).all()
    tasks = []
    for e in enrollments:
        bootcamp = db.query(Bootcamp).filter(Bootcamp.id == e.bootcamp_id).first()
        if not bootcamp or not bootcamp.is_active:
            continue
        day_number = (today - e.start_date).days + 1
        if day_number < 1 or day_number > bootcamp.days:
            continue
        day_form = db.query(DayForm).filter(
            DayForm.bootcamp_id == bootcamp.id, DayForm.day_number == day_number
        ).first()
        if not day_form:
            continue
        existing = db.query(Submission).filter(
            Submission.enrollment_id == e.id, Submission.day_number == day_number
        ).first()
        tasks.append({
            "enrollment": e, "bootcamp": bootcamp, "day_form": day_form,
            "day_number": day_number, "submitted": existing is not None,
        })
    return templates.TemplateResponse("user/today.html", {
        "request": request, "user": current_user, "app_name": APP_NAME, "tasks": tasks,
    })


@router.get("/form/{enrollment_id}/{day}")
async def fill_form(request: Request, enrollment_id: int, day: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id, Enrollment.user_id == current_user.id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="训练营不存在")
    bootcamp = db.query(Bootcamp).filter(Bootcamp.id == enrollment.bootcamp_id).first()
    day_form = db.query(DayForm).filter(DayForm.bootcamp_id == bootcamp.id, DayForm.day_number == day).first()
    if not day_form:
        raise HTTPException(status_code=404, detail="表单不存在")
    existing = db.query(Submission).filter(Submission.enrollment_id == enrollment_id, Submission.day_number == day).first()
    decrypted_existing = None
    if existing:
        class _Dec:
            def __init__(self, sub):
                self.id = sub.id
                self.day_number = sub.day_number
                self.submitted_at = sub.submitted_at
                self.review_status = sub.review_status
                self.review_comment = sub.review_comment
                self.answers = decrypt_data(sub.answers) if sub.review_status != "rejected" else decrypt_data(sub.answers)
        decrypted_existing = _Dec(existing)
    questions = day_form.questions or []
    has_reading = any(q.get("type") == "reading" for q in questions)
    # 如果是被拒绝的提交，显示表单让用户修改
    if has_reading and not decrypted_existing:
        return templates.TemplateResponse("user/camp_content.html", {
            "request": request, "user": current_user, "app_name": APP_NAME,
            "enrollment": enrollment, "bootcamp": bootcamp, "day_form": day_form,
            "day_number": day, "questions_json": questions,
        })
    return templates.TemplateResponse("user/form.html", {
        "request": request, "user": current_user, "app_name": APP_NAME,
        "enrollment": enrollment, "bootcamp": bootcamp, "day_form": day_form,
        "day_number": day, "existing": decrypted_existing,
    })


@router.post("/form/{enrollment_id}/{day}")
async def submit_form(request: Request, enrollment_id: int, day: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id, Enrollment.user_id == current_user.id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="训练营不存在")
    existing = db.query(Submission).filter(Submission.enrollment_id == enrollment_id, Submission.day_number == day).first()
    # 如果已通过或待审核，不允许重新提交
    if existing and existing.review_status != "rejected":
        return RedirectResponse(f"/user/form/{enrollment_id}/{day}", status_code=302)
    # 如果是被拒绝的提交，删除旧记录以便重新提交
    if existing and existing.review_status == "rejected":
        db.delete(existing)
        db.commit()
    # 检查是否需要按顺序提交
    if day > 1:
        prev_submission = db.query(Submission).filter(
            Submission.enrollment_id == enrollment_id,
            Submission.day_number == day - 1,
            Submission.review_status == "approved"
        ).first()
        if not prev_submission:
            raise HTTPException(status_code=400, detail="请先完成并等待通过前一天的表单")
    # 检查必填项
    day_form = db.query(DayForm).filter(
        DayForm.bootcamp_id == enrollment.bootcamp_id, DayForm.day_number == day
    ).first()
    form_data = await request.form()
    answers = {}
    for key, value in form_data.multi_items():
        if key.startswith("q_"):
            answers[key] = value
    if day_form:
        for q in day_form.questions:
            qid = q["id"]
            if q["type"] == "multiple":
                answers[qid] = form_data.getlist(f"q_{qid}")
            elif q["type"] == "likert":
                val = form_data.get(f"q_{qid}")
                answers[qid] = int(val) if val else None
            else:
                if qid not in answers:
                    answers[qid] = form_data.get(f"q_{qid}", "")
            # 验证必填项
            if q.get("required") and q["type"] != "reading":
                answer = answers.get(qid)
                if not answer or (isinstance(answer, str) and not answer.strip()) or (isinstance(answer, list) and len(answer) == 0):
                    return templates.TemplateResponse("user/form.html", {
                        "request": request, "user": current_user, "app_name": APP_NAME,
                        "enrollment": enrollment, "bootcamp": db.query(Bootcamp).filter(Bootcamp.id == enrollment.bootcamp_id).first(),
                        "day_form": day_form, "day_number": day, "existing": None,
                        "error": f"题目「{q.get('label', '')}」为必填项",
                    })
    encrypted_answers = encrypt_data(answers)
    submission = Submission(
        enrollment_id=enrollment_id,
        day_number=day,
        answers=encrypted_answers,
        review_status="pending"
    )
    db.add(submission)
    db.commit()
    _check_and_award_badges(db, current_user, enrollment)
    return RedirectResponse(f"/user/history/{enrollment_id}", status_code=302)


@router.post("/api/verify-answer")
async def verify_answer(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    try:
        body = await request.json()
        enrollment_id = body.get("enrollment_id")
        day_number = body.get("day_number")
        question_id = body.get("question_id")
        answer = body.get("answer")
        if not all([enrollment_id, day_number, question_id]):
            return JSONResponse(status_code=400, content={"correct": False, "message": "参数不完整"})
        enrollment = db.query(Enrollment).filter(
            Enrollment.id == int(enrollment_id), Enrollment.user_id == current_user.id
        ).first()
        if not enrollment:
            return JSONResponse(status_code=404, content={"correct": False, "message": "训练营不存在"})
        day_form = db.query(DayForm).filter(
            DayForm.bootcamp_id == enrollment.bootcamp_id, DayForm.day_number == int(day_number)
        ).first()
        if not day_form:
            return JSONResponse(status_code=404, content={"correct": False, "message": "表单不存在"})
        target_q = None
        for q in (day_form.questions or []):
            if q.get("id") == question_id:
                target_q = q
                break
        if not target_q:
            return JSONResponse(status_code=404, content={"correct": False, "message": "题目不存在"})
        correct = target_q.get("correct")
        if correct is None:
            return JSONResponse(content={"correct": True, "message": "该题无需验证"})
        if target_q["type"] == "single":
            is_correct = answer == correct
        elif target_q["type"] == "multiple":
            if isinstance(answer, list) and isinstance(correct, list):
                is_correct = set(answer) == set(correct)
            else:
                is_correct = False
        else:
            is_correct = True
        if is_correct:
            return JSONResponse(content={"correct": True, "message": "回答正确！"})
        else:
            return JSONResponse(content={"correct": False, "message": "回答有误，请再试一次"})
    except Exception as e:
        logger.exception("验证答案失败: %s", e)
        return JSONResponse(status_code=500, content={"correct": False, "message": "验证失败，请稍后重试"})


@router.get("/bootcamps")
async def browse_bootcamps(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        bootcamps = db.query(Bootcamp).filter(Bootcamp.is_active == True).order_by(Bootcamp.created_at.desc()).all()
        my_enrollments = db.query(Enrollment).filter(Enrollment.user_id == current_user.id).all()
        enrolled_bootcamp_ids = {e.bootcamp_id for e in my_enrollments}
        bootcamp_list = []
        for b in bootcamps:
            enrolled = b.id in enrolled_bootcamp_ids
            enrollment = next((e for e in my_enrollments if e.bootcamp_id == b.id), None)
            bootcamp_list.append({"bootcamp": b, "enrolled": enrolled, "enrollment": enrollment})
        return templates.TemplateResponse("user/bootcamps.html", {
            "request": request, "user": current_user, "app_name": APP_NAME,
            "bootcamps": bootcamp_list,
        })
    except Exception as e:
        logger.exception("加载训练营列表失败 (user_id=%d): %s", current_user.id, e)
        raise HTTPException(status_code=500, detail="加载训练营列表时发生错误")


@router.post("/bootcamp/{bootcamp_id}/join")
async def join_bootcamp(request: Request, bootcamp_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    try:
        bootcamp = db.query(Bootcamp).filter(Bootcamp.id == bootcamp_id, Bootcamp.is_active == True).first()
        if not bootcamp:
            raise HTTPException(status_code=404, detail="训练营不存在或未发布")
        existing = db.query(Enrollment).filter(
            Enrollment.user_id == current_user.id, Enrollment.bootcamp_id == bootcamp_id
        ).first()
        if existing:
            return RedirectResponse("/user/dashboard", status_code=302)
        enrollment = Enrollment(
            user_id=current_user.id,
            bootcamp_id=bootcamp_id,
            start_date=date.today(),
        )
        db.add(enrollment)
        db.commit()
        return RedirectResponse("/user/dashboard", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("加入训练营失败 (user_id=%d, bootcamp_id=%d): %s", current_user.id, bootcamp_id, e)
        raise HTTPException(status_code=500, detail="加入训练营时发生错误")


@router.get("/progress")
async def my_progress(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enrollments = db.query(Enrollment).filter(Enrollment.user_id == current_user.id).all()
    bootcamp_data = []
    for e in enrollments:
        bootcamp = db.query(Bootcamp).filter(Bootcamp.id == e.bootcamp_id).first()
        if not bootcamp:
            continue
        completed = db.query(Submission).filter(Submission.enrollment_id == e.id).count()
        percentage = int((completed / bootcamp.days * 100)) if bootcamp.days > 0 else 0
        bootcamp_data.append({"enrollment": e, "bootcamp": bootcamp, "percentage": percentage, "completed": completed})
    return templates.TemplateResponse("user/dashboard.html", {
        "request": request, "user": current_user, "app_name": APP_NAME, "bootcamp_data": bootcamp_data, "show_all": True,
    })


@router.get("/history/{enrollment_id}")
async def history(request: Request, enrollment_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id, Enrollment.user_id == current_user.id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="训练营不存在")
    bootcamp = db.query(Bootcamp).filter(Bootcamp.id == enrollment.bootcamp_id).first()
    submissions = db.query(Submission).filter(Submission.enrollment_id == enrollment_id).order_by(Submission.day_number).all()
    day_forms = {}
    for df in db.query(DayForm).filter(DayForm.bootcamp_id == bootcamp.id).all():
        day_forms[df.day_number] = df
    records = []
    for s in submissions:
        df = day_forms.get(s.day_number)
        decrypted_answers = decrypt_data(s.answers) if isinstance(s.answers, str) else s.answers
        record_submission = {
            "id": s.id,
            "day_number": s.day_number,
            "submitted_at": s.submitted_at,
            "answers": decrypted_answers
        }
        records.append({"submission": record_submission, "day_form": df})
    return templates.TemplateResponse("user/history.html", {
        "request": request, "user": current_user, "app_name": APP_NAME,
        "enrollment": enrollment, "bootcamp": bootcamp, "records": records,
    })


@router.get("/profile")
async def profile_page(request: Request, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse("user/dashboard.html", {
        "request": request, "user": current_user, "app_name": APP_NAME, "show_profile": True,
    })


@router.post("/profile")
async def update_profile(request: Request, nickname: str = Form(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    nickname = sanitize_text(nickname)
    if not nickname:
        return RedirectResponse("/user/profile", status_code=302)
    current_user.nickname = nickname
    db.commit()
    return RedirectResponse("/user/profile", status_code=302)


@router.post("/password")
async def update_password(request: Request, current_password: str = Form(...), new_password: str = Form(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    if not verify_password(current_password, current_user.hashed_password):
        return templates.TemplateResponse("user/dashboard.html", {
            "request": request, "user": current_user, "app_name": APP_NAME, "show_profile": True, "pwd_error": "当前密码错误",
        })
    pwd_valid, pwd_error = validate_password_strength(new_password)
    if not pwd_valid:
        return templates.TemplateResponse("user/dashboard.html", {
            "request": request, "user": current_user, "app_name": APP_NAME, "show_profile": True, "pwd_error": pwd_error,
        })
    current_user.hashed_password = get_password_hash(new_password)
    db.commit()
    return RedirectResponse("/user/profile", status_code=302)


@router.get("/badges")
async def badges_page(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    all_badges = db.query(Badge).all()
    user_badges = db.query(UserBadge).filter(UserBadge.user_id == current_user.id).all()
    badge_map = {ub.badge_id: ub for ub in user_badges}
    earned = []
    unearned = []
    for b in all_badges:
        if b.id in badge_map:
            earned.append({"badge": b, "user_badge": badge_map[b.id]})
        else:
            unearned.append(b)
    return templates.TemplateResponse("user/badges.html", {
        "request": request, "user": current_user, "app_name": APP_NAME,
        "earned_badges": earned, "unearned_badges": unearned,
    })


@router.post("/notification-toggle")
async def notification_toggle(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    current_user.notification_enabled = not current_user.notification_enabled
    db.commit()
    return RedirectResponse("/user/profile", status_code=302)


def _check_and_award_badges(db: Session, user: User, enrollment: Enrollment):
    from config import BADGE_STREAK_3_DAYS, BADGE_STREAK_7_DAYS
    submissions = db.query(Submission).filter(Submission.enrollment_id == enrollment.id).all()
    submitted_days = {s.day_number for s in submissions}
    bootcamp = db.query(Bootcamp).filter(Bootcamp.id == enrollment.bootcamp_id).first()
    if not bootcamp:
        return
    today = date.today()
    today_number = (today - enrollment.start_date).days + 1
    
    all_badges = db.query(Badge).all()
    badges_by_type = {}
    for badge in all_badges:
        badge_type = badge.criteria.get("type") if badge.criteria else None
        if badge_type:
            if badge_type not in badges_by_type:
                badges_by_type[badge_type] = []
            badges_by_type[badge_type].append(badge)
    
    first_badges = badges_by_type.get("first_submission", [])
    first_badge = first_badges[0] if first_badges else None
    if first_badge and len(submissions) >= 1:
        existing = db.query(UserBadge).filter(
            UserBadge.user_id == user.id, UserBadge.badge_id == first_badge.id,
            UserBadge.enrollment_id == enrollment.id
        ).first()
        if not existing:
            db.add(UserBadge(user_id=user.id, badge_id=first_badge.id, enrollment_id=enrollment.id))
    streak = 0
    check_date = today
    for _ in range(bootcamp.days):
        d = (check_date - enrollment.start_date).days + 1
        if d < 1:
            break
        if d in submitted_days:
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break
    streak_badges = badges_by_type.get("streak", [])
    for sb in streak_badges:
        required_days = sb.criteria.get("days", 3)
        if streak >= required_days:
            existing = db.query(UserBadge).filter(
                UserBadge.user_id == user.id, UserBadge.badge_id == sb.id,
                UserBadge.enrollment_id == enrollment.id
            ).first()
            if not existing:
                db.add(UserBadge(user_id=user.id, badge_id=sb.id, enrollment_id=enrollment.id))
    if len(submitted_days) >= bootcamp.days:
        complete_badges = badges_by_type.get("bootcamp_complete", [])
        complete_badge = complete_badges[0] if complete_badges else None
        if complete_badge:
            existing = db.query(UserBadge).filter(
                UserBadge.user_id == user.id, UserBadge.badge_id == complete_badge.id,
                UserBadge.enrollment_id == enrollment.id
            ).first()
            if not existing:
                db.add(UserBadge(user_id=user.id, badge_id=complete_badge.id, enrollment_id=enrollment.id))
    db.commit()
