from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    nickname = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="user", nullable=False)
    notification_enabled = Column(Boolean, default=True)
    student_id = Column(String, nullable=True)
    college = Column(String, nullable=True)
    grade = Column(String, nullable=True)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    # 审核员相关字段
    specialty = Column(String, nullable=True)  # 专业领域，用于智能分配
    is_active = Column(Boolean, default=True)  # 账户是否启用
    max_concurrent_tasks = Column(Integer, default=10)  # 最大并发任务数
