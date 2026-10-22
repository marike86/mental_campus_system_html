from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from auth import require_reviewer, require_admin, verify_csrf
from database import get_db
from models.user import User
from models.enrollment import Enrollment
from models.bootcamp import Bootcamp
from models.batch import Batch
from models.submission import Submission
from models.workflow import SubmissionAttempt, DayFormVersion
from models.review_assignment import ReviewAssignment
from services import reviews
from services.clock import now
from templates_config import templates
from utils.crypto import decrypt_data

router = APIRouter(tags=["review"])


@router.get("/review/pending")
@router.get("/admin/assignments")
async def workbench(request: Request, view: str='public', camp: int=None, batch: int=None, overdue: bool=False, page: int=1,
                    reviewer=Depends(require_reviewer), db: Session=Depends(get_db)):
    if view not in ('public','mine','completed','all') or page<1:
        raise HTTPException(400, "筛选参数无效")
    admin = reviewer.role in ('admin','super_admin')
    if view=='all' and not admin:
        raise HTTPException(403, "需要管理员权限")
    query = db.query(Submission, SubmissionAttempt, Enrollment, Bootcamp).join(SubmissionAttempt, SubmissionAttempt.submission_id==Submission.id if view=='completed' else Submission.current_attempt_id==SubmissionAttempt.id).join(Enrollment, Submission.enrollment_id==Enrollment.id).join(Bootcamp, Enrollment.bootcamp_id==Bootcamp.id)
    if view=='completed':
        query = query.filter(SubmissionAttempt.review_status.in_(['approved','rejected']))
        if not admin:
            query = query.filter(SubmissionAttempt.reviewer_id==reviewer.id)
    else:
        query = query.filter(SubmissionAttempt.review_status=='pending')
        assigned = db.query(ReviewAssignment.attempt_id).filter_by(status='pending')
        if view=='public':
            query = query.filter(~SubmissionAttempt.id.in_(assigned))
        elif view=='mine':
            query = query.join(ReviewAssignment, ReviewAssignment.attempt_id==SubmissionAttempt.id).filter(ReviewAssignment.status=='pending', ReviewAssignment.reviewer_id==reviewer.id)
    if camp:
        query = query.filter(Enrollment.bootcamp_id==camp)
    if batch:
        query = query.filter(Enrollment.batch_id==batch)
    if overdue:
        query = query.filter(SubmissionAttempt.submitted_at < now()-timedelta(hours=48))
    total = query.count()
    rows = query.order_by(SubmissionAttempt.submitted_at).offset((page-1)*20).limit(20).all()
    records = [dict(sub=sub, attempt=attempt, enrollment=e, camp=c, overdue=attempt.review_status=='pending' and attempt.submitted_at < now()-timedelta(hours=48)) for sub,attempt,e,c in rows]
    return templates.TemplateResponse('review/workbench.html', dict(request=request, user=reviewer, records=records, view=view,
        page=page, total=total, admin=admin, reviewers=db.query(User).filter_by(role='reviewer',is_active=True).all() if admin else [],
        camps=db.query(Bootcamp).all(), batches=db.query(Batch).all()))


@router.get("/review/{submission_id}")
async def detail(request: Request, submission_id: int, attempt_id: int=None, reviewer=Depends(require_reviewer), db: Session=Depends(get_db)):
    sub, current = reviews.current_attempt(db, submission_id)
    attempt = db.get(SubmissionAttempt, attempt_id) if attempt_id else current
    if not attempt or attempt.submission_id!=sub.id:
        raise HTTPException(404, "提交轮次不存在")
    reviews.authorize_detail(db, sub, attempt, reviewer)
    enrollment = db.get(Enrollment, sub.enrollment_id)
    version = db.get(DayFormVersion, attempt.version_id)
    answers = decrypt_data(attempt.answers)
    from types import SimpleNamespace
    display = SimpleNamespace(id=sub.id, day_number=sub.day_number, review_status=attempt.review_status,
        submitted_at=attempt.submitted_at, reviewed_at=attempt.reviewed_at, review_comment=attempt.review_comment)
    return templates.TemplateResponse('review/detail.html', dict(request=request, user=reviewer, submission=display,
        attempt=attempt, version=version, is_current=attempt.id==current.id, user_id=enrollment.user_id,
        bootcamp_name=db.get(Bootcamp,enrollment.bootcamp_id).name,
        questions_with_answers=[dict(question=q,answer=answers.get(q['id'],'')) for q in version.questions]))


@router.post('/review/{submission_id}/claim')
async def claim(request: Request, submission_id: int, reviewer=Depends(require_reviewer), db: Session=Depends(get_db), csrf=Depends(verify_csrf)):
    if reviewer.role!='reviewer':
        raise HTTPException(400, "管理员可以直接审核或指定审核员")
    form = await request.form()
    reviews.assign(db, submission_id, reviewer.id, reviewer, form.get('attempt_id',''))
    db.commit()
    return RedirectResponse(f'/review/{submission_id}',303)


@router.post('/review/{submission_id}/transfer')
async def transfer(request: Request, submission_id: int, admin=Depends(require_admin), db: Session=Depends(get_db), csrf=Depends(verify_csrf)):
    form = await request.form()
    try:
        reviewer_id=int(form['reviewer_id'])
    except (ValueError,KeyError):
        raise HTTPException(400, "请选择审核员")
    reviews.assign(db, submission_id, reviewer_id, admin, form.get('attempt_id',''))
    db.commit()
    return RedirectResponse('/admin/assignments?view=all',303)


@router.post('/review/{submission_id}/approve')
async def approve(request: Request, submission_id: int, reviewer=Depends(require_reviewer), db: Session=Depends(get_db), csrf=Depends(verify_csrf)):
    form = await request.form()
    reviews.decide(db, submission_id, form.get('attempt_id',''), reviewer, 'approved', form.get('comment',''))
    db.commit()
    return RedirectResponse('/review/pending?view=mine',303)


@router.post('/review/{submission_id}/reject')
async def reject(request: Request, submission_id: int, reviewer=Depends(require_reviewer), db: Session=Depends(get_db), csrf=Depends(verify_csrf)):
    form = await request.form()
    reviews.decide(db, submission_id, form.get('attempt_id',''), reviewer, 'rejected', form.get('comment',''))
    db.commit()
    return RedirectResponse('/review/pending?view=mine',303)
