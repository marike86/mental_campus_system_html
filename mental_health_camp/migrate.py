"""Explicit migration: python migrate.py [--backup PATH]. Never invoked by workers."""
import argparse
import copy
import sqlite3
from pathlib import Path
from sqlalchemy import inspect, text
from database import engine, Base, SessionLocal
from models import user, bootcamp, day_form, enrollment, submission, batch, badge, user_badge, audit_log, review_assignment
from models.workflow import WorkflowSchema, DayFormVersion, EnrollmentDay, SubmissionAttempt
from services.clock import now

SCHEMA_VERSION = 3


def preflight(connection):
    tables = set(inspect(connection).get_table_names())
    problems = []
    for table, group in [("enrollments", "user_id,bootcamp_id"), ("submissions", "enrollment_id,day_number"), ("day_forms", "bootcamp_id,day_number")]:
        if table in tables:
            rows = connection.execute(text(f"SELECT group_concat(id) FROM {table} GROUP BY {group} HAVING count(*)>1")).all()
            problems += [f"{table} 重复记录 ID: {r[0]}" for r in rows]
    links = [("enrollments", "user_id", "users"), ("enrollments", "bootcamp_id", "bootcamps"),
             ("submissions", "enrollment_id", "enrollments"), ("day_forms", "bootcamp_id", "bootcamps"),
             ("review_assignments", "submission_id", "submissions"), ("review_assignments", "reviewer_id", "users")]
    for table, col, parent in links:
        if table in tables and parent in tables:
            rows = connection.execute(text(f"SELECT c.id FROM {table} c LEFT JOIN {parent} p ON c.{col}=p.id WHERE p.id IS NULL")).all()
            problems += [f"{table} 孤立记录 ID: {r[0]}" for r in rows]
    if problems:
        raise RuntimeError("\n".join(problems))


def migrate(backup_path=None):
    tables = inspect(engine).get_table_names()
    with engine.connect() as connection:
        preflight(connection)
        if "workflow_schema" in tables:
            installed = connection.execute(text("SELECT version FROM workflow_schema WHERE id=1")).scalar()
            if installed == SCHEMA_VERSION:
                return False
            if installed not in (None, 1, 2):
                raise RuntimeError("不支持的数据库版本")
    if tables and engine.url.database not in (None, ":memory:"):
        destination = Path(backup_path or (str(engine.url.database) + now().strftime('.%Y%m%d%H%M%S.backup')))
        if destination.exists() or destination.resolve() == Path(engine.url.database).resolve():
            raise RuntimeError("备份路径必须是新文件")
        with sqlite3.connect(engine.url.database) as source, sqlite3.connect(destination) as target:
            source.backup(target)
    additions = {
        "audit_logs": {"event_type":"VARCHAR", "actor_role":"VARCHAR", "operation_id":"VARCHAR", "camp_id":"INTEGER", "batch_id":"INTEGER"},
        "users": {"specialty": "VARCHAR", "is_active": "BOOLEAN DEFAULT 1", "max_concurrent_tasks": "INTEGER DEFAULT 10"},
        "enrollments": {"status": "VARCHAR DEFAULT 'approved' NOT NULL"},
        "submissions": {"review_status": "VARCHAR DEFAULT 'approved' NOT NULL", "reviewer_id": "INTEGER", "review_comment": "TEXT", "reviewed_at": "DATETIME", "current_attempt_id": "INTEGER REFERENCES submission_attempts(id)"},
        "review_assignments": {"attempt_id": "INTEGER REFERENCES submission_attempts(id)"},
    }
    with engine.begin() as connection:
        for table, columns in additions.items():
            if table not in tables:
                continue
            existing = {c['name'] for c in inspect(connection).get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        Base.metadata.create_all(connection)
        for column in ("event_type","operation_id","camp_id","batch_id"):
            connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_audit_logs_{column} ON audit_logs({column})"))
        # Existing SQLite tables need indexes added explicitly.
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_submission_day ON submissions(enrollment_id,day_number)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_enrollment_camp ON enrollments(user_id,bootcamp_id)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_day_form ON day_forms(bootcamp_id,day_number)"))
    with SessionLocal() as db:
        versions = {}
        for form in db.query(day_form.DayForm).all():
            version = db.query(DayFormVersion).filter_by(day_form_id=form.id).first()
            if not version:
                version = DayFormVersion(day_form_id=form.id, version=1, questions=copy.deepcopy(form.questions or []),
                                         published_at=now(), legacy=True)
                db.add(version)
                db.flush()
            versions[(form.bootcamp_id, form.day_number)] = version
        for sub in db.query(submission.Submission).all():
            if sub.current_attempt_id:
                continue
            enrolled = db.get(enrollment.Enrollment, sub.enrollment_id)
            version = versions.get((enrolled.bootcamp_id, sub.day_number))
            if not version:
                raise RuntimeError(f"提交 {sub.id} 缺少对应表单；请恢复表单后重新迁移")
            db.add(EnrollmentDay(enrollment_id=enrolled.id, day_number=sub.day_number, version_id=version.id))
            attempt = SubmissionAttempt(submission_id=sub.id, round_number=1, version_id=version.id,
                                        answers=sub.answers, submitted_at=sub.submitted_at, review_status=sub.review_status,
                                        reviewer_id=sub.reviewer_id, review_comment=sub.review_comment,
                                        reviewed_at=sub.reviewed_at, legacy=True)
            db.add(attempt)
            db.flush()
            sub.current_attempt_id = attempt.id
            assignments = db.query(review_assignment.ReviewAssignment).filter_by(submission_id=sub.id).order_by(review_assignment.ReviewAssignment.id.desc()).all()
            active = False
            for assignment in assignments:
                assignment.attempt_id = attempt.id
                if assignment.status == "pending":
                    if active or sub.review_status != "pending":
                        assignment.status = "expired"
                    else:
                        active = True
            if sub.review_status == "pending":
                sub.reviewer_id = next((a.reviewer_id for a in assignments if a.status == "pending"), None)
        db.merge(WorkflowSchema(id=1, version=SCHEMA_VERSION, installed_at=now()))
        db.commit()
    with engine.begin() as connection:
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_active_attempt_assignment ON review_assignments(attempt_id) WHERE status='pending'"))
        connection.execute(text("""CREATE TRIGGER IF NOT EXISTS immutable_published_questions
            BEFORE UPDATE OF questions, version, day_form_id ON day_form_versions
            BEGIN SELECT RAISE(ABORT, 'Published content is immutable'); END"""))
        connection.execute(text("""CREATE TRIGGER IF NOT EXISTS protect_used_version
            BEFORE DELETE ON day_form_versions
            WHEN EXISTS(SELECT 1 FROM enrollment_days WHERE version_id=OLD.id)
              OR EXISTS(SELECT 1 FROM submission_attempts WHERE version_id=OLD.id)
            BEGIN SELECT RAISE(ABORT, 'Version is in use'); END"""))
    return True


def require_current_schema():
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version FROM workflow_schema WHERE id=1")).scalar()
    except Exception as exc:
        raise RuntimeError("数据库需要迁移，请先运行 python migrate.py") from exc
    if version != SCHEMA_VERSION:
        raise RuntimeError("数据库版本不匹配，请运行 python migrate.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup")
    args = parser.parse_args()
    print("迁移完成" if migrate(args.backup) else "数据库已是最新版本")
