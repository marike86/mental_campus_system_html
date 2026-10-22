from models.enrollment import Enrollment
from models.submission import Submission
from models.review_assignment import ReviewAssignment
from models.workflow import Notification, SubmissionAttempt, EnrollmentDay, ParticipationDay, DayFormVersion
from models.user_badge import UserBadge
from services.reviews import release_reviewer
from services.versions import write_lock


def delete_user_data(db, user_id):
    write_lock(db)
    release_reviewer(db,user_id)
    ids=[e.id for e in db.query(Enrollment).filter_by(user_id=user_id)]
    subs=[s.id for s in db.query(Submission).filter(Submission.enrollment_id.in_(ids))]
    attempts=[a.id for a in db.query(SubmissionAttempt).filter(SubmissionAttempt.submission_id.in_(subs))]
    db.query(Notification).filter((Notification.user_id==user_id) | Notification.attempt_id.in_(attempts)).delete(synchronize_session=False)
    db.query(ReviewAssignment).filter(ReviewAssignment.submission_id.in_(subs)).delete(synchronize_session=False)
    db.query(ReviewAssignment).filter_by(reviewer_id=user_id).delete(synchronize_session=False)
    db.query(ReviewAssignment).filter_by(assigned_by=user_id).update(dict(assigned_by=None),synchronize_session=False)
    db.query(Submission).filter(Submission.id.in_(subs)).update(dict(current_attempt_id=None),synchronize_session=False)
    db.query(SubmissionAttempt).filter(SubmissionAttempt.id.in_(attempts)).delete(synchronize_session=False)
    db.query(Submission).filter(Submission.id.in_(subs)).delete(synchronize_session=False)
    db.query(SubmissionAttempt).filter_by(reviewer_id=user_id).update(dict(reviewer_id=None),synchronize_session=False)
    db.query(Submission).filter_by(reviewer_id=user_id).update(dict(reviewer_id=None),synchronize_session=False)
    db.query(DayFormVersion).filter_by(published_by=user_id).update(dict(published_by=None),synchronize_session=False)
    db.query(EnrollmentDay).filter(EnrollmentDay.enrollment_id.in_(ids)).delete(synchronize_session=False)
    db.query(ParticipationDay).filter(ParticipationDay.enrollment_id.in_(ids)).delete(synchronize_session=False)
    db.query(UserBadge).filter_by(user_id=user_id).delete(synchronize_session=False)
    db.query(Enrollment).filter_by(user_id=user_id).delete(synchronize_session=False)
