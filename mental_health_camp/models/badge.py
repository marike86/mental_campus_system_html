from sqlalchemy import Column, Integer, String, Text, JSON, DateTime
from sqlalchemy.sql import func
from database import Base


class Badge(Base):
    __tablename__ = "badges"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    icon = Column(String, default="🏅")
    criteria = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now())
