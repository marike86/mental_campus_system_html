from datetime import date, timedelta
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
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
from auth import get_current_user, get_password_hash, verify_password
from config import APP_NAME
from templates_config import templates
from utils.crypto import encrypt_data, decrypt_data

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
                self.answers = decrypt_data(sub.answers)
        decrypted_existing = _Dec(existing)
    return templates.TemplateResponse("user/form.html", {
        "request": request, "user": current_user, "app_name": APP_NAME,
        "enrollment": enrollment, "bootcamp": bootcamp, "day_form": day_form,
        "day_number": day, "existing": decrypted_existing,
    })


@router.post("/form/{enrollment_id}/{day}")
async def submit_form(request: Request, enrollment_id: int, day: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id, Enrollment.user_id == current_user.id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="训练营不存在")
    existing = db.query(Submission).filter(Submission.enrollment_id == enrollment_id, Submission.day_number == day).first()
    if existing:
        return RedirectResponse(f"/user/form/{enrollment_id}/{day}", status_code=302)
    form_data = await request.form()
    answers = {}
    for key, value in form_data.multi_items():
        if key.startswith("q_"):
            answers[key] = value
    day_form = db.query(DayForm).filter(
        DayForm.bootcamp_id == enrollment.bootcamp_id, DayForm.day_number == day
    ).first()
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
    encrypted_answers = encrypt_data(answers)
    submission = Submission(enrollment_id=enrollment_id, day_number=day, answers=encrypted_answers)
    db.add(submission)
    db.commit()
    _check_and_award_badges(db, current_user, enrollment)
    return RedirectResponse(f"/user/history/{enrollment_id}", status_code=302)


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
async def update_profile(request: Request, nickname: str = Form(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.nickname = nickname
    db.commit()
    return RedirectResponse("/user/profile", status_code=302)


@router.post("/password")
async def update_password(request: Request, current_password: str = Form(...), new_password: str = Form(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(current_password, current_user.hashed_password):
        return templates.TemplateResponse("user/dashboard.html", {
            "request": request, "user": current_user, "app_name": APP_NAME, "show_profile": True, "pwd_error": "当前密码错误",
        })
    current_user.hashed_password = get_password_hash(new_password)
    db.commit()
    return RedirectResponse("/user/profile", status_code=300)


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
async def notification_toggle(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
