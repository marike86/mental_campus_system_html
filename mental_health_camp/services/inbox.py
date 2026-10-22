from datetime import timedelta
from sqlalchemy.dialects.sqlite import insert
from models.workflow import Notification, SubmissionAttempt
from models.submission import Submission
from models.enrollment import Enrollment
from models.review_assignment import ReviewAssignment
from models.user import User
from services.clock import now
from services.versions import write_lock


def notify(db, user_id, attempt_id, event, title, message=''):
    values = dict(user_id=user_id, attempt_id=attempt_id, event=event, title=title, message=message,
                  created_at=now(), dedupe_key=f'{attempt_id}:{event}:{user_id}')
    db.execute(insert(Notification).values(**values).on_conflict_do_nothing(index_elements=['dedupe_key']))


def review_result(db, sub, attempt, result, comment):
    enrollment = db.get(Enrollment, sub.enrollment_id)
    notify(db, enrollment.user_id, attempt.id, result,
           f'第 {sub.day_number} 天 · 第 {attempt.round_number} 次提交' + ('已通过' if result=='approved' else '需修改'), comment)


def overdue_scan(db):
    write_lock(db)
    admins = [u.id for u in db.query(User).filter(User.role.in_(['admin','super_admin']))]
    pending = db.query(Submission, SubmissionAttempt).join(SubmissionAttempt, Submission.current_attempt_id==SubmissionAttempt.id).filter(
        SubmissionAttempt.review_status=='pending', SubmissionAttempt.legacy==False,
        SubmissionAttempt.submitted_at < now()-timedelta(hours=48)).all()
    for sub, attempt in pending:
        assignment = db.query(ReviewAssignment).filter_by(attempt_id=attempt.id, status='pending').first()
        recipients = set(admins + ([assignment.reviewer_id] if assignment else []))
        for user_id in recipients:
            notify(db, user_id, attempt.id, 'overdue', f'第 {sub.day_number} 天作业待审核超过 48 小时', '请检查审核队列并安排处理。')
    return len(pending)


def present(db, notification, actor):
    attempt = db.get(SubmissionAttempt, notification.attempt_id)
    sub = db.get(Submission, attempt.submission_id)
    current = attempt.id == sub.current_attempt_id
    if actor.role in ('admin','super_admin','reviewer') and notification.event=='overdue':
        # Link to queue rather than a former assignee's now-inaccessible detail.
        url, action = '/review/pending?view=mine' if actor.role=='reviewer' else '/admin/assignments?view=all', '查看审核队列'
        next_url = None
    else:
        url = f'/user/form/{sub.enrollment_id}/{sub.day_number}'
        action = '修改后重提' if current and sub.review_status=='rejected' else '查看当前记录'
        next_url = f'/user/course/{sub.enrollment_id}' if notification.event=='approved' else None
    return dict(notification=notification, url=url, action=action, next_url=next_url)
