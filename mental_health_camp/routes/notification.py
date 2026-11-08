from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from models.enrollment import Enrollment
from utils.email import send_daily_reminder

router = APIRouter(tags=["notification"])


def check_and_send_reminders(db: Session):
    """给还有待办内容的学员发送每日提醒。

    已经用完当日份额的学员不再收到「去填写」链接，改为告知剩余内容明天继续。
    """
    from services.courses import progress
    users = db.query(User).filter(User.role == "user").all()
    sent_count = 0
    for user in users:
        if not getattr(user, "notification_enabled", True):
            continue
        enrollments = db.query(Enrollment).filter(Enrollment.user_id == user.id).all()
        pending_tasks = []
        deferred_tasks = []
        for e in enrollments:
            camp, days = progress(db, e)
            for item in days:
                if item["status"] == "approved":
                    continue
                entry = dict(bootcamp_name=camp.name, day_number=item["day"], form_url=item["url"])
                if item["actionable"]:
                    pending_tasks.append(entry)
                elif item.get("daily_blocked"):
                    deferred_tasks.append(entry)
        if not pending_tasks and not deferred_tasks:
            continue
        note = ""
        if not pending_tasks:
            note = f"今日已完成一份内容，剩余 {len(deferred_tasks)} 份明天继续。"
        if send_daily_reminder(user.email, user.nickname, pending_tasks, deferred_tasks, note):
            sent_count += 1
    return sent_count
