from sqlalchemy import Column, Integer, String, ForeignKey, Date, DateTime, Index
from sqlalchemy.sql import func
from database import Base


class Enrollment(Base):
    __tablename__ = "enrollments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    bootcamp_id = Column(Integer, ForeignKey("bootcamps.id"), nullable=False, index=True)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=True, index=True)
    status = Column(String, default="approved", nullable=False)  # pending / approved / rejected
    start_date = Column(Date, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index('idx_enrollment_user_bootcamp', 'user_id', 'bootcamp_id'),
    )
