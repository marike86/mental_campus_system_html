from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, Date, DateTime
from sqlalchemy.sql import func
from database import Base


class Batch(Base):
    __tablename__ = "batches"

    id = Column(Integer, primary_key=True, index=True)
    bootcamp_id = Column(Integer, ForeignKey("bootcamps.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
