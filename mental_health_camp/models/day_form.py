from sqlalchemy import Column, Integer, ForeignKey, JSON
from database import Base


class DayForm(Base):
    __tablename__ = "day_forms"

    id = Column(Integer, primary_key=True, index=True)
    bootcamp_id = Column(Integer, ForeignKey("bootcamps.id"), nullable=False)
    day_number = Column(Integer, nullable=False)
    questions = Column(JSON, nullable=False, default=list)
