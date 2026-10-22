from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from models import user, bootcamp, day_form, enrollment, submission, batch, badge, user_badge, audit_log, review_assignment
    from models import workflow
    Base.metadata.create_all(bind=engine)


@event.listens_for(engine, "connect")
def sqlite_settings(connection, record):
    if engine.dialect.name == "sqlite":
        connection.execute("PRAGMA busy_timeout=10000")
