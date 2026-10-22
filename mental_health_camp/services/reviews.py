from fastapi import HTTPException
from sqlalchemy import update
from models.user import User
from models.submission import Submission
from models.enrollment import Enrollment
from models.review_assignment import ReviewAssignment
from models.workflow import SubmissionAttempt
from services.clock import now
from services.versions import write_lock


def current_attempt(db, submission_id, attempt_id=None):
    sub = db.query(Submission).populate_existing().filter_by(id=submission_id).first()
    if not sub:
        raise HTTPException(404, "提交记录不存在")
    if attempt_id is not None and str(sub.current_attempt_id) != str(attempt_id):
        raise HTTPException(409, "此提交已更新，请刷新任务")
    attempt = db.get(SubmissionAttempt, sub.current_attempt_id) if sub.current_attempt_id else None
    if not attempt:
        raise HTTPException(409, "缺少提交轮次，请检查迁移")
    return sub, attempt


def active_assignment(db, attempt_id):
    return db.query(ReviewAssignment).filter_by(attempt_id=attempt_id, status='pending').first()


def authorize_detail(db, sub, attempt, actor):
    if actor.role in ('admin','super_admin'):
        return
    assignment = active_assignment(db, attempt.id)
    if attempt.review_status != 'pending':
        if attempt.reviewer_id==actor.id:
            return
    elif assignment and assignment.reviewer_id==actor.id:
        return
    raise HTTPException(403, "请先领取此任务；仅可访问自己的审核记录")


def assign(db, submission_id, reviewer_id, actor, attempt_id=None):
    write_lock(db)
    sub, attempt = current_attempt(db, submission_id, attempt_id)
    if attempt.review_status != 'pending':
        raise HTTPException(409, "该轮提交已审核")
    reviewer = db.query(User).populate_existing().filter_by(id=reviewer_id, role='reviewer', is_active=True).first()
    if not reviewer:
        raise HTTPException(400, "审核员不可用")
    existing = active_assignment(db, attempt.id)
    is_admin = actor.role in ('admin', 'super_admin')
    if not is_admin and (reviewer_id!=actor.id or existing):
        raise HTTPException(409, "任务已被领取")
    if existing and existing.reviewer_id==reviewer_id:
        if not is_admin:
            raise HTTPException(409, "任务已被领取")
        return existing
    count = db.query(ReviewAssignment).filter_by(reviewer_id=reviewer_id, status='pending').count()
    if count >= reviewer.max_concurrent_tasks:
        raise HTTPException(409, "审核员已达到任务容量")
    if existing:
        existing.status, existing.completed_at = 'transferred', now()
        db.flush()
    assignment = ReviewAssignment(submission_id=sub.id, attempt_id=attempt.id, reviewer_id=reviewer.id,
                                  assigned_by=actor.id, assignment_type='manual' if is_admin else 'claim',
                                  status='pending', assigned_at=now())
    db.add(assignment)
    sub.reviewer_id = reviewer.id
    db.flush()
    return assignment


def decide(db, submission_id, attempt_id, actor, result, comment=''):
    write_lock(db)
    sub, attempt = current_attempt(db, submission_id, attempt_id)
    if attempt.review_status != 'pending':
        raise HTTPException(409, "该轮提交已经审核")
    authorize_detail(db, sub, attempt, actor)
    if result=='rejected' and not comment.strip():
        raise HTTPException(400, "驳回时请填写修改建议")
    stamp = now()
    changed = db.execute(update(SubmissionAttempt).where(SubmissionAttempt.id==attempt.id, SubmissionAttempt.review_status=='pending')
                         .values(review_status=result, reviewer_id=actor.id, review_comment=comment.strip(), reviewed_at=stamp)).rowcount
    if changed!=1:
        raise HTTPException(409, "任务已由其他人处理")
    sub.review_status, sub.reviewer_id, sub.review_comment, sub.reviewed_at = result, actor.id, comment.strip(), stamp
    for assignment in db.query(ReviewAssignment).filter_by(attempt_id=attempt.id, status='pending'):
        assignment.status = 'completed' if assignment.reviewer_id==actor.id else 'expired'
        assignment.completed_at = stamp
    db.flush()
    if result=='approved':
        from routes.user_routes import _check_and_award_badges
        enrollment = db.get(Enrollment, sub.enrollment_id)
        _check_and_award_badges(db, db.get(User, enrollment.user_id), enrollment)
    from services.inbox import review_result
    review_result(db, sub, attempt, result, comment.strip())
    return sub, attempt


def release_reviewer(db, reviewer_id):
    for assignment in db.query(ReviewAssignment).filter_by(reviewer_id=reviewer_id, status='pending'):
        assignment.status, assignment.completed_at = 'released', now()
        sub = db.get(Submission, assignment.submission_id)
        if sub and sub.current_attempt_id==assignment.attempt_id and sub.review_status=='pending':
            sub.reviewer_id = None
