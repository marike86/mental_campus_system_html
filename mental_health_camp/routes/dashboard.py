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
    today = date.today()
    today_number = (today - enrollment.start_date).days + 1
    submissions = db.query(Submission).filter(
        Submission.enrollment_id == enrollment_id
    ).all()
    submitted_days = {s.day_number for s in submissions}
    calendar = []
    for d in range(1, bootcamp.days + 1):
        day_date = enrollment.start_date + timedelta(days=d - 1)
        status = "future"
        if d <= today_number:
            if d in submitted_days:
                status = "completed"
            else:
                status = "missed"
        calendar.append({"day": d, "date": day_date.isoformat(), "status": status})
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
    day_forms = {}
    for df in db.query(DayForm).filter(DayForm.bootcamp_id == bootcamp.id).all():
        day_forms[df.day_number] = df
    likert_series = {}
    for s in sorted(submissions, key=lambda x: x.day_number):
        df = day_forms.get(s.day_number)
        if not df:
            continue
        answers = decrypt_data(s.answers) if isinstance(s.answers, str) else s.answers
        for q in df.questions:
            if q["type"] == "likert":
                qid = q["id"]
                val = answers.get(qid)
                if val is not None:
                    if qid not in likert_series:
                        likert_series[qid] = {
                            "label": q["label"],
                            "labels": q.get("labels", []),
                            "data": []
                        }
                    likert_series[qid]["data"].append({
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
    labels = []
    values = []
    for s in submissions:
        df = day_forms.get(s.day_number)
        if not df:
            continue
        answers = decrypt_data(s.answers) if isinstance(s.answers, str) else s.answers
        for q in df.questions:
            if q["id"] == question_id and q["type"] == "likert":
                val = answers.get(question_id)
                if val is not None:
                    labels.append(f"第{s.day_number}天")
                    values.append(val)
                break
    return JSONResponse({"labels": labels, "values": values})
