from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String, nullable=False)
    target_type = Column(String, nullable=False)
    target_id = Column(Integer, nullable=True)
    detail = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    event_type = Column(String, index=True)
    actor_role = Column(String)
    operation_id = Column(String, index=True)
    camp_id = Column(Integer, index=True)
    batch_id = Column(Integer, index=True)


class BulkOperation(Base):
    __tablename__ = "bulk_operations"
    request_id = Column(String, primary_key=True)
    actor_id = Column(Integer, nullable=False)
    fingerprint = Column(String, nullable=False)
    result = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
