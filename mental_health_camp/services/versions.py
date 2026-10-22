import copy
import re
from fastapi import HTTPException
from sqlalchemy import func, text
from models.day_form import DayForm
from models.workflow import DayFormVersion, EnrollmentDay, SubmissionAttempt
from services.clock import now


def write_lock(db):
    # First write acquires SQLite's database write lock, serializing capacity/claim checks.
    db.execute(text("UPDATE workflow_schema SET version=version WHERE id=1"))


def validate_questions(questions):
    if not isinstance(questions, list) or not questions:
        raise HTTPException(400, "发布内容至少需要一道题目或阅读材料")
    ids = set()
    for q in questions:
        if not isinstance(q, dict):
            raise HTTPException(400, "题目格式错误")
        qid = q.get("id")
        if not isinstance(qid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", qid) or qid in ids:
            raise HTTPException(400, "题目 ID 必须唯一且只包含字母、数字、下划线或短横线")
        ids.add(qid)
        kind = q.get("type")
        if kind not in ("text", "single", "multiple", "likert", "reading"):
            raise HTTPException(400, "不支持的题型")
        if not isinstance(q.get("label", ""), str):
            raise HTTPException(400, "题目标题格式错误")
        if kind in ("single", "multiple"):
            options = q.get("options")
            if not isinstance(options, list) or not options or any(not isinstance(x, str) or not x.strip() for x in options) or len(set(options)) != len(options):
                raise HTTPException(400, "选项不能为空或重复")
            correct = q.get("correct")
            if correct is not None:
                selected = correct if kind == "multiple" else [correct]
                if not isinstance(selected, list) or any(x not in options for x in selected):
                    raise HTTPException(400, "正确答案必须属于选项")
        if kind == "likert":
            lo, hi = q.get("min", 1), q.get("max", 5)
            if type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi <= 100:
                raise HTTPException(400, "量表范围必须为 0–100 内的整数")
            labels = q.get("labels", [])
            if not isinstance(labels, list) or any(not isinstance(x, str) for x in labels) or (labels and len(labels) != hi-lo+1):
                raise HTTPException(400, "量表标签数须与范围一致")
    return questions


def latest_version(db, day_form_id):
    return db.query(DayFormVersion).filter_by(day_form_id=day_form_id).order_by(DayFormVersion.version.desc()).first()


def publish(db, day_form, admin_id):
    write_lock(db)
    if not db.is_modified(day_form):
        db.refresh(day_form)
    validate_questions(day_form.questions)
    previous = latest_version(db, day_form.id)
    version = DayFormVersion(day_form_id=day_form.id, version=(previous.version+1 if previous else 1),
                             questions=copy.deepcopy(day_form.questions), published_by=admin_id, published_at=now())
    db.add(version)
    db.flush()
    return version


def bound_version(db, enrollment_id, day):
    binding = db.query(EnrollmentDay).filter_by(enrollment_id=enrollment_id, day_number=day).first()
    return db.get(DayFormVersion, binding.version_id) if binding else None


def submission_questions(db, submission):
    attempt = db.get(SubmissionAttempt, submission.current_attempt_id) if submission.current_attempt_id else None
    if attempt:
        return db.get(DayFormVersion, attempt.version_id).questions
    # Only for pre-migration fixtures; production startup rejects unmigrated databases.
    from models.enrollment import Enrollment
    enrollment = db.get(Enrollment, submission.enrollment_id)
    form = db.query(DayForm).filter_by(bootcamp_id=enrollment.bootcamp_id, day_number=submission.day_number).first()
    return form.questions if form else []
