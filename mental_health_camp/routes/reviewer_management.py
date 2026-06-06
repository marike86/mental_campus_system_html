import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func as sql_func
from database import get_db
from models.user import User
from models.submission import Submission
from models.review_assignment import ReviewAssignment
from auth import require_super_admin, get_password_hash
from config import APP_NAME
from templates_config import templates
from routes.audit import log_admin_action

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reviewer_management"])


@router.get("/super-admin/reviewers")
async def reviewer_list(request: Request, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """审核员列表页面"""
    try:
        reviewers = db.query(User).filter(User.role == "reviewer").order_by(User.created_at.desc()).all()
        
        # 获取每个审核员的统计信息
        reviewer_stats = []
        for reviewer in reviewers:
            # 总审核数
            total_reviews = db.query(Submission).filter(Submission.reviewer_id == reviewer.id).count()
            # 待审核任务数
            pending_tasks = db.query(ReviewAssignment).filter(
                ReviewAssignment.reviewer_id == reviewer.id,
                ReviewAssignment.status == "pending"
            ).count()
            # 已完成任务数
            completed_tasks = db.query(ReviewAssignment).filter(
                ReviewAssignment.reviewer_id == reviewer.id,
                ReviewAssignment.status == "completed"
            ).count()
            # 通过率
            approved_count = db.query(Submission).filter(
                Submission.reviewer_id == reviewer.id,
                Submission.review_status == "approved"
            ).count()
            approval_rate = int((approved_count / total_reviews * 100)) if total_reviews > 0 else 0
            
            reviewer_stats.append({
                "reviewer": reviewer,
                "total_reviews": total_reviews,
                "pending_tasks": pending_tasks,
                "completed_tasks": completed_tasks,
                "approval_rate": approval_rate,
            })
        
        return templates.TemplateResponse("super_admin/reviewers.html", {
            "request": request, "user": admin, "app_name": APP_NAME,
            "reviewer_stats": reviewer_stats,
        })
    except Exception as e:
        logger.exception("加载审核员列表失败: %s", e)
        raise HTTPException(status_code=500, detail="加载审核员列表时发生错误")


@router.get("/super-admin/reviewer/new")
async def new_reviewer_page(request: Request, admin: User = Depends(require_super_admin)):
    """创建审核员页面"""
    return templates.TemplateResponse("super_admin/reviewer_form.html", {
        "request": request, "user": admin, "app_name": APP_NAME,
        "reviewer": None, "mode": "create",
    })


@router.post("/super-admin/reviewer/new")
async def create_reviewer(request: Request, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """创建审核员"""
    try:
        form_data = await request.form()
        email = form_data.get("email", "").strip()
        nickname = form_data.get("nickname", "").strip()
        password = form_data.get("password", "")
        specialty = form_data.get("specialty", "").strip()
        max_concurrent_tasks_str = form_data.get("max_concurrent_tasks", "10")
        
        if not email:
            raise HTTPException(status_code=400, detail="邮箱不能为空")
        if not nickname:
            raise HTTPException(status_code=400, detail="昵称不能为空")
        if not password or len(password) < 6:
            raise HTTPException(status_code=400, detail="密码长度不能少于6位")
        
        try:
            max_concurrent_tasks = int(max_concurrent_tasks_str)
        except (TypeError, ValueError):
            max_concurrent_tasks = 10
        
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            raise HTTPException(status_code=400, detail="该邮箱已被注册")
        
        reviewer = User(
            email=email,
            nickname=nickname,
            hashed_password=get_password_hash(password),
            role="reviewer",
            specialty=specialty or None,
            max_concurrent_tasks=max_concurrent_tasks,
            is_active=True,
        )
        db.add(reviewer)
        db.commit()
        
        log_admin_action(db, admin.id, "创建审核员", "user", reviewer.id, {
            "email": email, "nickname": nickname, "specialty": specialty
        })
        return RedirectResponse("/super-admin/reviewers", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("创建审核员失败: %s", e)
        raise HTTPException(status_code=500, detail="创建审核员时发生错误")


@router.get("/super-admin/reviewer/{reviewer_id}")
async def reviewer_detail(request: Request, reviewer_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """审核员详情页面"""
    try:
        reviewer = db.query(User).filter(User.id == reviewer_id, User.role == "reviewer").first()
        if not reviewer:
            raise HTTPException(status_code=404, detail="审核员不存在")
        
        # 获取审核统计
        total_reviews = db.query(Submission).filter(Submission.reviewer_id == reviewer_id).count()
        approved_count = db.query(Submission).filter(
            Submission.reviewer_id == reviewer_id,
            Submission.review_status == "approved"
        ).count()
        rejected_count = db.query(Submission).filter(
            Submission.reviewer_id == reviewer_id,
            Submission.review_status == "rejected"
        ).count()
        approval_rate = int((approved_count / total_reviews * 100)) if total_reviews > 0 else 0
        
        # 获取当前待审核任务
        pending_assignments = db.query(ReviewAssignment).filter(
            ReviewAssignment.reviewer_id == reviewer_id,
            ReviewAssignment.status == "pending"
        ).order_by(ReviewAssignment.assigned_at.desc()).all()
        
        # 获取最近审核记录
        recent_reviews = db.query(Submission).filter(
            Submission.reviewer_id == reviewer_id
        ).order_by(Submission.reviewed_at.desc()).limit(20).all()
        
        return templates.TemplateResponse("super_admin/reviewer_detail.html", {
            "request": request, "user": admin, "app_name": APP_NAME,
            "reviewer": reviewer,
            "total_reviews": total_reviews,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "approval_rate": approval_rate,
            "pending_assignments": pending_assignments,
            "recent_reviews": recent_reviews,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("加载审核员详情失败: %s", e)
        raise HTTPException(status_code=500, detail="加载审核员详情时发生错误")


@router.get("/super-admin/reviewer/{reviewer_id}/edit")
async def edit_reviewer_page(request: Request, reviewer_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """编辑审核员页面"""
    reviewer = db.query(User).filter(User.id == reviewer_id, User.role == "reviewer").first()
    if not reviewer:
        raise HTTPException(status_code=404, detail="审核员不存在")
    return templates.TemplateResponse("super_admin/reviewer_form.html", {
        "request": request, "user": admin, "app_name": APP_NAME,
        "reviewer": reviewer, "mode": "edit",
    })


@router.post("/super-admin/reviewer/{reviewer_id}/edit")
async def update_reviewer(request: Request, reviewer_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """更新审核员信息"""
    try:
        reviewer = db.query(User).filter(User.id == reviewer_id, User.role == "reviewer").first()
        if not reviewer:
            raise HTTPException(status_code=404, detail="审核员不存在")
        
        form_data = await request.form()
        nickname = form_data.get("nickname", "").strip()
        specialty = form_data.get("specialty", "").strip()
        max_concurrent_tasks_str = form_data.get("max_concurrent_tasks", "10")
        new_password = form_data.get("new_password", "").strip()
        
        if not nickname:
            raise HTTPException(status_code=400, detail="昵称不能为空")
        
        try:
            max_concurrent_tasks = int(max_concurrent_tasks_str)
        except (TypeError, ValueError):
            max_concurrent_tasks = reviewer.max_concurrent_tasks
        
        reviewer.nickname = nickname
        reviewer.specialty = specialty or None
        reviewer.max_concurrent_tasks = max_concurrent_tasks
        
        if new_password and len(new_password) >= 6:
            reviewer.hashed_password = get_password_hash(new_password)
        
        db.commit()
        
        log_admin_action(db, admin.id, "编辑审核员", "user", reviewer_id, {
            "nickname": nickname, "specialty": specialty
        })
        return RedirectResponse(f"/super-admin/reviewer/{reviewer_id}", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("编辑审核员失败: %s", e)
        raise HTTPException(status_code=500, detail="编辑审核员时发生错误")


@router.post("/super-admin/reviewer/{reviewer_id}/toggle")
async def toggle_reviewer(request: Request, reviewer_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """启用/禁用审核员"""
    try:
        reviewer = db.query(User).filter(User.id == reviewer_id, User.role == "reviewer").first()
        if not reviewer:
            raise HTTPException(status_code=404, detail="审核员不存在")
        
        reviewer.is_active = not reviewer.is_active
        db.commit()
        
        action = "启用审核员" if reviewer.is_active else "禁用审核员"
        log_admin_action(db, admin.id, action, "user", reviewer_id)
        return RedirectResponse("/super-admin/reviewers", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("切换审核员状态失败: %s", e)
        raise HTTPException(status_code=500, detail="操作失败")


@router.get("/super-admin/assignments")
async def assignment_list(request: Request, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """审核任务分配管理页面"""
    try:
        # 获取所有待审核的提交
        pending_submissions = db.query(Submission).filter(
            Submission.review_status == "pending"
        ).order_by(Submission.submitted_at.desc()).all()
        
        # 获取所有活跃的审核员
        active_reviewers = db.query(User).filter(
            User.role == "reviewer",
            User.is_active == True
        ).all()
        
        # 获取每个审核员的当前任务数
        reviewer_workload = {}
        for reviewer in active_reviewers:
            pending_count = db.query(ReviewAssignment).filter(
                ReviewAssignment.reviewer_id == reviewer.id,
                ReviewAssignment.status == "pending"
            ).count()
            reviewer_workload[reviewer.id] = {
                "pending_count": pending_count,
                "max_tasks": reviewer.max_concurrent_tasks,
                "specialty": reviewer.specialty,
            }
        
        # 获取已分配的任务
        assignments = db.query(ReviewAssignment).filter(
            ReviewAssignment.status == "pending"
        ).all()
        assigned_submission_ids = {a.submission_id for a in assignments}
        
        return templates.TemplateResponse("super_admin/assignments.html", {
            "request": request, "user": admin, "app_name": APP_NAME,
            "pending_submissions": pending_submissions,
            "active_reviewers": active_reviewers,
            "reviewer_workload": reviewer_workload,
            "assigned_submission_ids": assigned_submission_ids,
        })
    except Exception as e:
        logger.exception("加载审核任务分配页面失败: %s", e)
        raise HTTPException(status_code=500, detail="加载页面时发生错误")


@router.post("/super-admin/assign")
async def assign_review_task(request: Request, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """手动分配审核任务"""
    try:
        form_data = await request.form()
        submission_id_str = form_data.get("submission_id", "")
        reviewer_id_str = form_data.get("reviewer_id", "")
        
        if not submission_id_str or not reviewer_id_str:
            raise HTTPException(status_code=400, detail="请选择提交和审核员")
        
        try:
            submission_id = int(submission_id_str)
            reviewer_id = int(reviewer_id_str)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="ID必须为数字")
        
        # 检查提交是否存在且待审核
        submission = db.query(Submission).filter(
            Submission.id == submission_id,
            Submission.review_status == "pending"
        ).first()
        if not submission:
            raise HTTPException(status_code=404, detail="提交不存在或已审核")
        
        # 检查审核员是否存在且活跃
        reviewer = db.query(User).filter(
            User.id == reviewer_id,
            User.role == "reviewer",
            User.is_active == True
        ).first()
        if not reviewer:
            raise HTTPException(status_code=404, detail="审核员不存在或已禁用")
        
        # 检查是否已分配
        existing_assignment = db.query(ReviewAssignment).filter(
            ReviewAssignment.submission_id == submission_id,
            ReviewAssignment.status == "pending"
        ).first()
        if existing_assignment:
            # 更新分配
            existing_assignment.reviewer_id = reviewer_id
            existing_assignment.assigned_by = admin.id
            existing_assignment.assignment_type = "manual"
        else:
            # 创建新分配
            assignment = ReviewAssignment(
                submission_id=submission_id,
                reviewer_id=reviewer_id,
                assigned_by=admin.id,
                assignment_type="manual",
                status="pending",
            )
            db.add(assignment)
        
        # 同时更新提交的审核员
        submission.reviewer_id = reviewer_id
        db.commit()
        
        log_admin_action(db, admin.id, "手动分配审核任务", "submission", submission_id, {
            "reviewer_id": reviewer_id
        })
        return RedirectResponse("/super-admin/assignments", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("分配审核任务失败: %s", e)
        raise HTTPException(status_code=500, detail="分配任务时发生错误")


@router.post("/super-admin/auto-assign")
async def auto_assign_tasks(request: Request, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """智能自动分配审核任务"""
    try:
        # 获取所有待审核且未分配的提交
        pending_submissions = db.query(Submission).filter(
            Submission.review_status == "pending",
            Submission.reviewer_id.is_(None)
        ).all()
        
        # 获取所有活跃的审核员
        active_reviewers = db.query(User).filter(
            User.role == "reviewer",
            User.is_active == True
        ).all()
        
        if not active_reviewers:
            raise HTTPException(status_code=400, detail="没有可用的审核员")
        
        assigned_count = 0
        
        for submission in pending_submissions:
            # 找到负载最低的审核员
            best_reviewer = None
            min_workload = float('inf')
            
            for reviewer in active_reviewers:
                # 检查当前任务数
                current_tasks = db.query(ReviewAssignment).filter(
                    ReviewAssignment.reviewer_id == reviewer.id,
                    ReviewAssignment.status == "pending"
                ).count()
                
                # 检查是否超过最大任务数
                if current_tasks >= reviewer.max_concurrent_tasks:
                    continue
                
                # 简单的负载均衡：选择任务最少的审核员
                if current_tasks < min_workload:
                    min_workload = current_tasks
                    best_reviewer = reviewer
            
            if best_reviewer:
                # 创建分配
                assignment = ReviewAssignment(
                    submission_id=submission.id,
                    reviewer_id=best_reviewer.id,
                    assigned_by=admin.id,
                    assignment_type="auto",
                    status="pending",
                )
                db.add(assignment)
                
                # 更新提交的审核员
                submission.reviewer_id = best_reviewer.id
                assigned_count += 1
        
        db.commit()
        
        log_admin_action(db, admin.id, "智能分配审核任务", "assignment", None, {
            "assigned_count": assigned_count
        })
        return RedirectResponse("/super-admin/assignments", status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("智能分配任务失败: %s", e)
        raise HTTPException(status_code=500, detail="智能分配时发生错误")


@router.get("/super-admin/review-stats")
async def review_statistics(request: Request, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """审核统计页面"""
    try:
        # 总体统计
        total_submissions = db.query(Submission).count()
        pending_count = db.query(Submission).filter(Submission.review_status == "pending").count()
        approved_count = db.query(Submission).filter(Submission.review_status == "approved").count()
        rejected_count = db.query(Submission).filter(Submission.review_status == "rejected").count()
        
        # 各审核员统计
        reviewers = db.query(User).filter(User.role == "reviewer").all()
        reviewer_stats = []
        for reviewer in reviewers:
            reviewed = db.query(Submission).filter(Submission.reviewer_id == reviewer.id).count()
            approved = db.query(Submission).filter(
                Submission.reviewer_id == reviewer.id,
                Submission.review_status == "approved"
            ).count()
            rejected = db.query(Submission).filter(
                Submission.reviewer_id == reviewer.id,
                Submission.review_status == "rejected"
            ).count()
            approval_rate = int((approved / reviewed * 100)) if reviewed > 0 else 0
            
            reviewer_stats.append({
                "reviewer": reviewer,
                "reviewed": reviewed,
                "approved": approved,
                "rejected": rejected,
                "approval_rate": approval_rate,
            })
        
        # 按审核数量排序
        reviewer_stats.sort(key=lambda x: x["reviewed"], reverse=True)
        
        return templates.TemplateResponse("super_admin/review_stats.html", {
            "request": request, "user": admin, "app_name": APP_NAME,
            "total_submissions": total_submissions,
            "pending_count": pending_count,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "reviewer_stats": reviewer_stats,
        })
    except Exception as e:
        logger.exception("加载审核统计失败: %s", e)
        raise HTTPException(status_code=500, detail="加载统计时发生错误")
