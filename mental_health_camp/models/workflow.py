"""Versioned learning, immutable submission rounds and inbox records."""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, JSON, Boolean, UniqueConstraint, Index, text
from database import Base


class WorkflowSchema(Base):
    __tablename__ = "workflow_schema"
    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False)
    installed_at = Column(DateTime, nullable=False)


class DayFormVersion(Base):
    __tablename__ = "day_form_versions"
    id = Column(Integer, primary_key=True)
    day_form_id = Column(Integer, ForeignKey("day_forms.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    questions = Column(JSON, nullable=False)
    published_by = Column(Integer, ForeignKey("users.id"))
    published_at = Column(DateTime, nullable=False)
    legacy = Column(Boolean, nullable=False, default=False)
    __table_args__ = (UniqueConstraint("day_form_id", "version"),)


class EnrollmentDay(Base):
    __tablename__ = "enrollment_days"
    id = Column(Integer, primary_key=True)
    enrollment_id = Column(Integer, ForeignKey("enrollments.id"), nullable=False, index=True)
    day_number = Column(Integer, nullable=False)
    version_id = Column(Integer, ForeignKey("day_form_versions.id"), nullable=False)
    started_at = Column(DateTime)  # NULL for imported history with unknown start time
    __table_args__ = (UniqueConstraint("enrollment_id", "day_number"),)


class SubmissionAttempt(Base):
    __tablename__ = "submission_attempts"
    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False, index=True)
    round_number = Column(Integer, nullable=False)
    version_id = Column(Integer, ForeignKey("day_form_versions.id"), nullable=False)
    answers = Column(Text, nullable=False)
    submitted_at = Column(DateTime, nullable=False, index=True)
    review_status = Column(String, nullable=False, default="pending")
    reviewer_id = Column(Integer, ForeignKey("users.id"))
    review_comment = Column(Text)
    reviewed_at = Column(DateTime)
    legacy = Column(Boolean, nullable=False, default=False)
    __table_args__ = (UniqueConstraint("submission_id", "round_number"),)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    event = Column(String, nullable=False)
    attempt_id = Column(Integer, ForeignKey("submission_attempts.id"), nullable=False)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False)
    read_at = Column(DateTime)
    dedupe_key = Column(String, unique=True, nullable=False)
