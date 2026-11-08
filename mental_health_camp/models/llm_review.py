"""大模型自动审核：全局接口配置与逐次调用记录。"""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean, Float
from sqlalchemy.sql import func
from database import Base


class LLMConfig(Base):
    """全局单行配置（id=1），由超级管理员在页面上维护。"""
    __tablename__ = "llm_configs"

    id = Column(Integer, primary_key=True, default=1)
    enabled = Column(Boolean, nullable=False, default=False)
    base_url = Column(String, nullable=False, default="")
    api_key_encrypted = Column(Text, nullable=False, default="")
    model = Column(String, nullable=False, default="")
    timeout = Column(Integer, nullable=False, default=30)
    retries = Column(Integer, nullable=False, default=1)
    temperature = Column(Float, nullable=False, default=0.0)
    max_tokens = Column(Integer, nullable=False, default=800)
    auto_decision = Column(Boolean, nullable=False, default=True)
    prompt_template = Column(Text, nullable=False, default="")
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class LLMReviewLog(Base):
    """每次自动审核的调用记录；失败时用于降级排查。"""
    __tablename__ = "llm_review_logs"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=True, index=True)
    attempt_id = Column(Integer, ForeignKey("submission_attempts.id"), nullable=True, index=True)
    # approved / rejected / manual（转人工）/ error（调用失败降级）/ disabled（未启用或配置不完整）
    status = Column(String, nullable=False)
    passed = Column(Boolean, nullable=True)
    risk_level = Column(String, nullable=True)
    reason = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    model = Column(String, nullable=True)
    raw_response = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
