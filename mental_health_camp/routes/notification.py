from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from models.bootcamp import Bootcamp
from models.enrollment import Enrollment
from models.day_form import DayForm
from models.submission import Submission
from utils.email import send_daily_reminder

router = APIRouter(tags=["notification"])


def check_and_send_reminders(db: Session):
    today = date.today()
    users = db.query(User).filter(User.role == "user").all()
    sent_count = 0
    for user in users:
        if not getattr(user, "notification_enabled", True):
            continue
        enrollments = db.query(Enrollment).filter(Enrollment.user_id == user.id).all()
        pending_tasks = []
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
            if not existing:
                pending_tasks.append({
                    "bootcamp_name": bootcamp.name,
                    "day_number": day_number,
                    "form_url": f"/user/form/{e.id}/{day_number}",
                })
        if pending_tasks:
            if send_daily_reminder(user.email, user.nickname, pending_tasks):
                sent_count += 1
    return sent_count
