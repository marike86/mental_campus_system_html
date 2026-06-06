from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean
from sqlalchemy.sql import func
from database import Base


class ReviewAssignment(Base):
    """审核任务分配表"""
    __tablename__ = "review_assignments"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False, index=True)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    assigned_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # 分配者ID，智能分配时为空
    assignment_type = Column(String, default="auto", nullable=False)  # auto(智能分配) / manual(手动分配)
    status = Column(String, default="pending", nullable=False)  # pending/completed/expired
    assigned_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)
