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

from types import SimpleNamespace
from services.clock import local_date
from services import courses
from services.versions import bound_version, submission_questions
from models.workflow import SubmissionAttempt, DayFormVersion
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
        completed = db.query(Submission).filter(Submission.enrollment_id == e.id, Submission.review_status == "approved").count()
        percentage = int((completed / bootcamp.days * 100)) if bootcamp.days > 0 else 0
        bootcamp_data.append({"enrollment": e, "bootcamp": bootcamp, "percentage": percentage, "completed": completed})
    return templates.TemplateResponse("user/dashboard.html", {
        "request": request, "user": current_user, "app_name": APP_NAME, "bootcamp_data": bootcamp_data,
    })


@router.get("/today")
async def today_tasks(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enrollments = db.query(Enrollment).filter_by(user_id=current_user.id).all()
    groups = []
    for enrollment in enrollments:
        camp, items = courses.progress(db, enrollment)
        groups.append(dict(enrollment=enrollment, camp=camp, items=[x for x in items if x['status'] != 'approved']))
    return templates.TemplateResponse("user/courses.html", dict(request=request, user=current_user, groups=groups))


@router.get("/course/{enrollment_id}")
async def course_overview(request: Request, enrollment_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enrollment = courses.owned_enrollment(db, current_user.id, enrollment_id)
    camp, items = courses.progress(db, enrollment)
    return templates.TemplateResponse("user/courses.html", dict(request=request, user=current_user, groups=[dict(enrollment=enrollment, camp=camp, items=items)]))


@router.get("/api/progress/{enrollment_id}")
async def course_progress(enrollment_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enrollment = courses.owned_enrollment(db, current_user.id, enrollment_id)
    camp, items = courses.progress(db, enrollment)
    return dict(days=items, completed_days=sum(x['status']=='approved' for x in items), total_days=camp.days,
                next_action=next((x for x in items if x['actionable']), None))


@router.post("/course/{enrollment_id}/{day}/start")
async def start_course(enrollment_id: int, day: int, current_user: User=Depends(get_current_user), db: Session=Depends(get_db), csrf=Depends(verify_csrf)):
    enrollment = courses.owned_enrollment(db, current_user.id, enrollment_id)
    courses.start(db, enrollment, day)
    db.commit()
    return RedirectResponse(f"/user/form/{enrollment_id}/{day}", 303)


def form_context(db, enrollment, day, current_user, request):
    camp, items = courses.progress(db, enrollment)
    item = next((x for x in items if x['day']==day), None)
    if item is None:
        raise HTTPException(404, "表单不存在")
    version = bound_version(db, enrollment.id, day)
    sub = db.query(Submission).filter_by(enrollment_id=enrollment.id, day_number=day).first()
    existing = None
    if sub:
        existing = SimpleNamespace(id=sub.id, day_number=day, answers=decrypt_data(sub.answers),
                                   review_status=sub.review_status, review_comment=sub.review_comment,
                                   submitted_at=sub.submitted_at)
    context = dict(request=request, user=current_user, app_name=APP_NAME, enrollment=enrollment, bootcamp=camp,
                   day_number=day, state=item, version=version, version_id=version.id if version else None, existing=existing,
                   draft_key=f"answers:{current_user.id}:{enrollment.id}:{day}:{version.id}" if version else "")
    if version:
        context.update(day_form=SimpleNamespace(questions=version.questions), questions_json=version.questions)
    return context


@router.get("/form/{enrollment_id}/{day}")
async def fill_form(request: Request, enrollment_id: int, day: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enrollment = courses.owned_enrollment(db, current_user.id, enrollment_id)
    context = form_context(db, enrollment, day, current_user, request)
    if not context['version'] or (context['existing'] is None and not context['state']['actionable']):
        return templates.TemplateResponse("user/start.html", context)
    reading = any(q.get('type')=='reading' for q in context['questions_json'])
    editable = context['state']['actionable']
    if reading and editable:
        return templates.TemplateResponse("user/camp_content.html", context)
    context['can_edit'] = editable
    return templates.TemplateResponse("user/form.html", context)


@router.post("/form/{enrollment_id}/{day}")
async def submit_form(request: Request, enrollment_id: int, day: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    enrollment = courses.owned_enrollment(db, current_user.id, enrollment_id)
    form = await request.form()
    try:
        submission = courses.submit(db, enrollment, day, form)
    except HTTPException as exc:
        if exc.status_code != 400:
            raise
        db.rollback()
        context = form_context(db, enrollment, day, current_user, request)
        answers = {}
        for q in context['version'].questions:
            key='q_'+q['id']
            answers[q['id']] = form.getlist(key) if q['type']=='multiple' else form.get(key,'')
        context.update(existing=SimpleNamespace(answers=answers,review_status='rejected',review_comment=''),can_edit=True,error=exc.detail)
        reading=any(q['type']=='reading' for q in context['version'].questions)
        return templates.TemplateResponse('user/camp_content.html' if reading else 'user/form.html',context,status_code=400)
    db.commit()
    return RedirectResponse(f"/user/history/{enrollment_id}?submitted_day={day}&submitted_attempt={submission.current_attempt_id}", 303)


@router.post("/api/verify-answer")
async def verify_answer(request: Request, current_user: User=Depends(get_current_user), db: Session=Depends(get_db), csrf=Depends(verify_csrf)):
    try:
        body = await request.json()
        enrollment_id, day = int(body['enrollment_id']), int(body['day_number'])
        qid, answer = body['question_id'], body.get('answer')
    except (ValueError, TypeError, KeyError):
        raise HTTPException(400, "参数不完整或格式错误")
    enrollment = courses.owned_enrollment(db, current_user.id, enrollment_id)
    courses.can_work(db, enrollment, day)
    version = bound_version(db, enrollment.id, day)
    if not version:
        raise HTTPException(409, "请先开始课程")
    question = next((q for q in version.questions if q['id']==qid), None)
    if not question:
        raise HTTPException(404, "题目不存在")
    correct = question.get('correct')
    is_correct = True
    if correct is not None:
        is_correct = (isinstance(answer,list) and all(isinstance(x,str) for x in answer) and set(answer)==set(correct)) if question['type']=='multiple' else answer==correct
    return dict(correct=is_correct, message="回答正确！" if is_correct else "回答有误，请再试一次")


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
            start_date=local_date(),
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
        completed = db.query(Submission).filter(Submission.enrollment_id == e.id, Submission.review_status == "approved").count()
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
    for sub in submissions:
        for attempt in db.query(SubmissionAttempt).filter_by(submission_id=sub.id).order_by(SubmissionAttempt.round_number):
            version = db.get(DayFormVersion, attempt.version_id)
            record = dict(id=sub.id, day_number=sub.day_number, submitted_at=attempt.submitted_at,
                          answers=decrypt_data(attempt.answers), review_status=attempt.review_status,
                          review_comment=attempt.review_comment, round_number=attempt.round_number, version=version.version,
                          legacy=version.legacy)
            records.append(dict(submission=record, day_form=SimpleNamespace(questions=version.questions)))
    clear_key = None
    submitted_day = request.query_params.get('submitted_day', '')
    submitted_attempt=request.query_params.get('submitted_attempt','')
    accepted=next((s for s in submissions if str(s.current_attempt_id)==submitted_attempt and s.review_status!='rejected'),None)
    if submitted_day.isdigit() and accepted and accepted.day_number==int(submitted_day):
        version = bound_version(db, enrollment.id, int(submitted_day))
        if version and any(s.day_number==int(submitted_day) for s in submissions):
            clear_key = f"answers:{current_user.id}:{enrollment.id}:{int(submitted_day)}:{version.id}"
    return templates.TemplateResponse("user/history.html", {
        "draft_key_to_clear": clear_key,
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
    from services.courses import streak
    submissions = db.query(Submission).filter_by(enrollment_id=enrollment.id, review_status='approved').all()
    camp = db.get(Bootcamp, enrollment.bootcamp_id)
    days = sorted({local_date(s.submitted_at) for s in submissions})
    longest = run = 0
    previous = None
    for day in days:
        run = run+1 if previous and day-previous==timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    for badge in db.query(Badge).all():
        criteria = badge.criteria or {}
        kind = criteria.get('type')
        earned = kind=='first_submission' and bool(submissions) or kind=='streak' and longest>=criteria.get('days',3) or kind=='bootcamp_complete' and len({s.day_number for s in submissions})>=camp.days
        if earned and not db.query(UserBadge).filter_by(user_id=user.id, badge_id=badge.id, enrollment_id=enrollment.id).first():
            db.add(UserBadge(user_id=user.id, badge_id=badge.id, enrollment_id=enrollment.id))
