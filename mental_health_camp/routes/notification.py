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
        from services.courses import progress
        for e in enrollments:
            camp, days = progress(db, e)
            for item in days:
                if item['actionable']:
                    pending_tasks.append(dict(bootcamp_name=camp.name, day_number=item['day'], form_url=item['url']))
        if pending_tasks:
            if send_daily_reminder(user.email, user.nickname, pending_tasks):
                sent_count += 1
    return sent_count
