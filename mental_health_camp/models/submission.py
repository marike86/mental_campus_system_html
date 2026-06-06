from sqlalchemy import Column, Integer, String, ForeignKey, Text, DateTime, Index
from sqlalchemy.sql import func
from database import Base


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    enrollment_id = Column(Integer, ForeignKey("enrollments.id"), nullable=False, index=True)
    day_number = Column(Integer, nullable=False)
    answers = Column(Text, nullable=False, default="{}")
    # 审核状态: pending(待审核), approved(通过), rejected(不通过)
    review_status = Column(String, default="approved", nullable=False)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    review_comment = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index('idx_submission_enrollment_day', 'enrollment_id', 'day_number'),
    )
