from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import update
from models.bootcamp import Bootcamp
from models.day_form import DayForm
from models.enrollment import Enrollment
from models.submission import Submission
from models.workflow import EnrollmentDay, DayFormVersion, SubmissionAttempt
from services.clock import now, local_date
from services.versions import bound_version, latest_version, write_lock
from utils.crypto import encrypt_data

LABELS = dict(future="未开始", locked="已锁定", available="可学习", pending="待审核", rejected="需修改", approved="已完成")


def owned_enrollment(db, user_id, enrollment_id):
    enrollment = db.query(Enrollment).filter_by(id=enrollment_id, user_id=user_id).first()
    if not enrollment:
        raise HTTPException(404, "训练营不存在")
    return enrollment


def states(enrollment, camp, submissions, published_days, today=None):
    today = today or local_date()
    result = []
    blocked = "训练营已停用" if not camp.is_active else "报名尚未批准" if enrollment.status != "approved" else "尚未设置开课日期" if not enrollment.start_date else ""
    for day in range(1, camp.days+1):
        scheduled = enrollment.start_date + timedelta(days=day-1) if enrollment.start_date else None
        sub = submissions.get(day)
        reason = blocked
        if sub:
            status = sub.review_status
        elif not scheduled or scheduled > today:
            status = "future"
            reason = reason or "尚未到计划日期"
        elif day > 1 and (day-1 not in submissions or submissions[day-1].review_status != "approved"):
            status = "locked"
            reason = reason or "请等待前一天审核通过"
        else:
            status = "available"
        if status in ("available", "rejected") and day not in published_days:
            reason = reason or "课程尚未发布"
        if status == "rejected" and scheduled and scheduled > today:
            reason = reason or "尚未到计划日期"
        actionable = status in ("available", "rejected") and not reason
        result.append(dict(day=day, status=status, label=LABELS[status], scheduled_date=scheduled.isoformat() if scheduled else None,
                           reason=reason, actionable=actionable, url=f"/user/form/{enrollment.id}/{day}"))
    return result


def progress(db, enrollment):
    camp = db.get(Bootcamp, enrollment.bootcamp_id)
    if not camp:
        raise HTTPException(404, "训练营不存在")
    subs = {s.day_number:s for s in db.query(Submission).filter_by(enrollment_id=enrollment.id)}
    published = {d.day_number for d in db.query(DayForm).join(DayFormVersion, DayFormVersion.day_form_id==DayForm.id).filter(DayForm.bootcamp_id==camp.id)}
    published.update(d.day_number for d in db.query(EnrollmentDay).filter_by(enrollment_id=enrollment.id))
    return camp, states(enrollment, camp, subs, published)


def can_work(db, enrollment, day):
    camp, items = progress(db, enrollment)
    item = next((x for x in items if x['day']==day), None)
    if item is None:
        raise HTTPException(404, "表单不存在")
    if not item['actionable']:
        raise HTTPException(409, item['reason'] or f"当前状态为{item['label']}")
    return camp


def start(db, enrollment, day):
    write_lock(db)
    can_work(db, enrollment, day)
    version = bound_version(db, enrollment.id, day)
    if version:
        return version
    form = db.query(DayForm).filter_by(bootcamp_id=enrollment.bootcamp_id, day_number=day).first()
    version = latest_version(db, form.id) if form else None
    if not version:
        raise HTTPException(409, "课程尚未发布")
    db.add(EnrollmentDay(enrollment_id=enrollment.id, day_number=day, version_id=version.id, started_at=now()))
    db.flush()
    return version


def parse_answers(questions, form):
    answers = {}
    for q in questions:
        qid, kind = q['id'], q['type']
        if kind == 'reading':
            continue
        value = form.getlist('q_'+qid) if kind=='multiple' else form.get('q_'+qid, '')
        if not isinstance(value, (str, list)):
            raise HTTPException(400, "答案格式错误")
        if kind=='likert':
            try:
                value = int(value) if value != '' else None
            except (ValueError, TypeError):
                raise HTTPException(400, "量表答案必须为整数")
            if value is not None and not q.get('min',1) <= value <= q.get('max',5):
                raise HTTPException(400, "量表答案超出范围")
        if kind in ('single','multiple'):
            values = value if isinstance(value,list) else ([value] if value else [])
            if any(v not in q.get('options',[]) for v in values):
                raise HTTPException(400, "答案不属于题目选项")
        if q.get('required') and (value is None or value=='' or value==[] or isinstance(value,str) and not value.strip()):
            raise HTTPException(400, f"题目「{q.get('label','')}」为必填项")
        correct = q.get('correct')
        if correct is not None and kind in ('single', 'multiple'):
            matches = set(value)==set(correct) if kind=='multiple' else value==correct
            if not matches:
                raise HTTPException(400, "请完成课程题目的正确作答")
        answers[qid] = value
    return answers


def submit(db, enrollment, day, form):
    write_lock(db)
    can_work(db, enrollment, day)
    version = bound_version(db, enrollment.id, day)
    if not version or str(version.id) != str(form.get('version_id','')):
        raise HTTPException(409, "课程版本不匹配，请重新打开课程")
    answers = parse_answers(version.questions, form)
    sub = db.query(Submission).filter_by(enrollment_id=enrollment.id, day_number=day).first()
    if not sub:
        sub = Submission(enrollment_id=enrollment.id, day_number=day, answers='{}', review_status='pending')
        db.add(sub)
        db.flush()
    previous = db.get(SubmissionAttempt, sub.current_attempt_id) if sub.current_attempt_id else None
    attempt = SubmissionAttempt(submission_id=sub.id, round_number=previous.round_number+1 if previous else 1,
                                version_id=version.id, answers=encrypt_data(answers), submitted_at=now(), review_status='pending')
    db.add(attempt)
    db.flush()
    sub.current_attempt_id = attempt.id
    sub.answers, sub.submitted_at, sub.review_status = attempt.answers, attempt.submitted_at, 'pending'
    sub.reviewer_id = sub.review_comment = sub.reviewed_at = None
    return sub


def streak(submissions, today=None):
    days = {local_date(s.submitted_at) for s in submissions if s.review_status=='approved'}
    current = today or local_date()
    if current not in days:
        current -= timedelta(days=1)
    count = 0
    while current in days:
        count += 1
        current -= timedelta(days=1)
    return count
