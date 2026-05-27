from sqlalchemy import Column, Integer, ForeignKey, Text, DateTime, Index
from sqlalchemy.sql import func
from database import Base


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    enrollment_id = Column(Integer, ForeignKey("enrollments.id"), nullable=False, index=True)
    day_number = Column(Integer, nullable=False)
    answers = Column(Text, nullable=False, default="{}")
    submitted_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index('idx_submission_enrollment_day', 'enrollment_id', 'day_number'),
    )
