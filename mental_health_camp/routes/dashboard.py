import json
from datetime import date, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from models.bootcamp import Bootcamp
from models.enrollment import Enrollment
from models.submission import Submission
from models.day_form import DayForm
from auth import get_current_user
from utils.crypto import decrypt_data
from services import courses
from services.versions import submission_questions
from services.clock import local_date
from types import SimpleNamespace
from models.workflow import SubmissionAttempt, DayFormVersion

router = APIRouter(prefix="/user/api", tags=["dashboard-api"])


@router.get("/dashboard-data/{enrollment_id}")
async def dashboard_data(enrollment_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enrollment = db.query(Enrollment).filter(
        Enrollment.id == enrollment_id, Enrollment.user_id == current_user.id
    ).first()
    if not enrollment:
        return JSONResponse({"error": "训练营不存在"}, status_code=404)
    bootcamp = db.query(Bootcamp).filter(Bootcamp.id == enrollment.bootcamp_id).first()
    if not bootcamp:
        return JSONResponse({"error": "训练营不存在"}, status_code=404)
    today = local_date()
    today_number = (today - enrollment.start_date).days + 1 if enrollment.start_date else 0
    submissions = db.query(Submission).filter(
        Submission.enrollment_id == enrollment_id
    ).all()
    _, items = courses.progress(db, enrollment)
    submitted_days = {s.day_number for s in submissions if s.review_status=='approved'}
    calendar = [dict(day=x['day'], date=x['scheduled_date'], status=x['status'], reason=x['reason']) for x in items]
    streak = courses.streak(submissions)
    day_forms = {}
    for df in db.query(DayForm).filter(DayForm.bootcamp_id == bootcamp.id).all():
        day_forms[df.day_number] = df
    likert_series = {}
    for s in sorted(submissions, key=lambda x: x.day_number):
        df = SimpleNamespace(questions=submission_questions(db, s))
        if not df:
            continue
        answers = decrypt_data(s.answers) if isinstance(s.answers, str) else s.answers
        for q in df.questions:
            if q["type"] == "likert":
                qid = q["id"]
                series_key = f"{s.current_attempt_id and db.get(SubmissionAttempt, s.current_attempt_id).version_id}:{qid}"
                val = answers.get(qid)
                if val is not None:
                    if series_key not in likert_series:
                        likert_series[series_key] = {
                            "label": q["label"],
                            "labels": q.get("labels", []),
                            "min": q.get("min",1),
                            "version_label": f"第{s.day_number}天 · 版本{db.get(DayFormVersion,db.get(SubmissionAttempt,s.current_attempt_id).version_id).version}" if s.current_attempt_id else "历史记录",
                            "data": []
                        }
                    likert_series[series_key]["data"].append({
                        "day": s.day_number,
                        "value": val
                    })
    return JSONResponse({
        "calendar": calendar,
        "streak": streak,
        "likert_series": likert_series,
        "total_days": bootcamp.days,
        "completed_days": len(submitted_days),
    })


@router.get("/likert-trend/{enrollment_id}/{question_id}")
async def likert_trend(enrollment_id: int, question_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enrollment = db.query(Enrollment).filter(
        Enrollment.id == enrollment_id, Enrollment.user_id == current_user.id
    ).first()
    if not enrollment:
        return JSONResponse({"error": "训练营不存在"}, status_code=404)
    bootcamp = db.query(Bootcamp).filter(Bootcamp.id == enrollment.bootcamp_id).first()
    day_forms = {}
    for df in db.query(DayForm).filter(DayForm.bootcamp_id == bootcamp.id).all():
        day_forms[df.day_number] = df
    submissions = db.query(Submission).filter(
        Submission.enrollment_id == enrollment_id
    ).order_by(Submission.day_number).all()
    series = {}
    for sub in submissions:
        attempt = db.get(SubmissionAttempt,sub.current_attempt_id) if sub.current_attempt_id else None
        for q in submission_questions(db,sub):
            if q['id']==question_id and q['type']=='likert':
                value=decrypt_data(sub.answers).get(question_id)
                if value is not None:
                    key=str(attempt.version_id if attempt else 'legacy')
                    row=series.setdefault(key,dict(version_id=attempt.version_id if attempt else None,label=q.get('label',''),labels=[],values=[]))
                    row['labels'].append(f'第{sub.day_number}天')
                    row['values'].append(value)
    single=next(iter(series.values())) if len(series)==1 else dict(labels=[],values=[])
    return JSONResponse(dict(labels=single['labels'],values=single['values'],series=series))
