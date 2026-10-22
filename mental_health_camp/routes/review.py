import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from models.submission import Submission
from models.enrollment import Enrollment
from models.bootcamp import Bootcamp
from models.day_form import DayForm
from models.review_assignment import ReviewAssignment
from auth import require_reviewer, verify_csrf
from config import APP_NAME
from templates_config import templates
from utils.crypto import decrypt_data

logger = logging.getLogger(__name__)

router = APIRouter(tags=["review"])


@router.get("/review/pending")
async def review_pending(request: Request, reviewer: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    """查看待审核的提交列表"""
    try:
        # 审核员只能看到用户ID，看不到详细信息
        pending_submissions = db.query(Submission).filter(
            Submission.review_status == "pending"
        ).order_by(Submission.submitted_at.desc()).all()

        submission_list = []
        for s in pending_submissions:
            enrollment = db.query(Enrollment).filter(Enrollment.id == s.enrollment_id).first()
            if not enrollment:
                continue
            bootcamp = db.query(Bootcamp).filter(Bootcamp.id == enrollment.bootcamp_id).first()
            # 审核员只能看到用户ID，不能看到用户详细信息
            submission_list.append({
                "submission": s,
                "user_id": enrollment.user_id,
                "bootcamp_name": bootcamp.name if bootcamp else "未知",
                "day_number": s.day_number,
            })

        return templates.TemplateResponse("review/pending.html", {
            "request": request, "user": reviewer, "app_name": APP_NAME,
            "submissions": submission_list,
        })
    except Exception as e:
        logger.exception("加载待审核列表失败: %s", e)
        raise HTTPException(status_code=500, detail="加载待审核列表时发生错误")


@router.get("/review/{submission_id}")
async def review_detail(request: Request, submission_id: int, reviewer: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    """查看提交详情并进行审核"""
    try:
        submission = db.query(Submission).filter(Submission.id == submission_id).first()
        if not submission:
            raise HTTPException(status_code=404, detail="提交记录不存在")

        enrollment = db.query(Enrollment).filter(Enrollment.id == submission.enrollment_id).first()
        if not enrollment:
            raise HTTPException(status_code=404, detail="报名记录不存在")

        bootcamp = db.query(Bootcamp).filter(Bootcamp.id == enrollment.bootcamp_id).first()
        day_form = db.query(DayForm).filter(
            DayForm.bootcamp_id == enrollment.bootcamp_id,
            DayForm.day_number == submission.day_number
        ).first()

        # 解密答案
        decrypted_answers = decrypt_data(submission.answers) if isinstance(submission.answers, str) else submission.answers

        # 构建题目和答案对照
        questions_with_answers = []
        if day_form and day_form.questions:
            from services.versions import submission_questions
            for q in submission_questions(db, submission):
                answer = decrypted_answers.get(q["id"], "")
                questions_with_answers.append({
                    "question": q,
                    "answer": answer,
                })

        return templates.TemplateResponse("review/detail.html", {
            "request": request, "user": reviewer, "app_name": APP_NAME,
            "submission": submission,
            "user_id": enrollment.user_id,
            "bootcamp_name": bootcamp.name if bootcamp else "未知",
            "questions_with_answers": questions_with_answers,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("加载审核详情失败: %s", e)
        raise HTTPException(status_code=500, detail="加载审核详情时发生错误")


@router.post("/review/{submission_id}/approve")
async def approve_submission(request: Request, submission_id: int, reviewer: User = Depends(require_reviewer), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    """审核通过"""
    try:
        submission = db.query(Submission).filter(Submission.id == submission_id).first()
        if not submission:
            raise HTTPException(status_code=404, detail="提交记录不存在")

        submission.review_status = "approved"
        submission.reviewer_id = reviewer.id
        submission.reviewed_at = datetime.now(timezone.utc)
        
        # 更新审核任务分配状态
        assignment = db.query(ReviewAssignment).filter(
            ReviewAssignment.submission_id == submission_id,
            ReviewAssignment.reviewer_id == reviewer.id,
            ReviewAssignment.status == "pending"
        ).first()
        if assignment:
            assignment.status = "completed"
            assignment.completed_at = datetime.now(timezone.utc)
        
        db.commit()

        return RedirectResponse("/review/pending", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("审核通过操作失败: %s", e)
        raise HTTPException(status_code=500, detail="审核操作失败")


@router.post("/review/{submission_id}/reject")
async def reject_submission(request: Request, submission_id: int, reviewer: User = Depends(require_reviewer), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    """审核不通过"""
    try:
        submission = db.query(Submission).filter(Submission.id == submission_id).first()
        if not submission:
            raise HTTPException(status_code=404, detail="提交记录不存在")

        form_data = await request.form()
        comment = form_data.get("comment", "").strip()

        submission.review_status = "rejected"
        submission.reviewer_id = reviewer.id
        submission.review_comment = comment
        submission.reviewed_at = datetime.now(timezone.utc)
        
        # 更新审核任务分配状态
        assignment = db.query(ReviewAssignment).filter(
            ReviewAssignment.submission_id == submission_id,
            ReviewAssignment.reviewer_id == reviewer.id,
            ReviewAssignment.status == "pending"
        ).first()
        if assignment:
            assignment.status = "completed"
            assignment.completed_at = datetime.now(timezone.utc)
        
        db.commit()

        return RedirectResponse("/review/pending", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("审核拒绝操作失败: %s", e)
        raise HTTPException(status_code=500, detail="审核操作失败")
