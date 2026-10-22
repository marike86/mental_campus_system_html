import math
from collections import defaultdict, Counter
from datetime import timedelta
from statistics import median
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import defer, load_only
from models.enrollment import Enrollment
from models.bootcamp import Bootcamp
from models.day_form import DayForm
from models.user import User
from models.submission import Submission
from models.workflow import SubmissionAttempt, DayFormVersion, EnrollmentDay, ParticipationDay, MetricsCoverage
from models.review_assignment import ReviewAssignment
from services.clock import now, local_date
from services.courses import states


def load_data(db, camp_id=None, batch_id=None):
    query = db.query(Enrollment).filter_by(status='approved')
    if camp_id:
        query=query.filter_by(bootcamp_id=camp_id)
    if batch_id:
        query=query.filter_by(batch_id=batch_id)
    enrollments=query.all()
    ids=[e.id for e in enrollments]
    by_id={e.id:e for e in enrollments}
    camps={c.id:c for c in db.query(Bootcamp).all()}
    users={u.id:u for u in db.query(User).options(load_only(User.id,User.nickname)).filter(User.id.in_([e.user_id for e in enrollments]))}
    subs=db.query(Submission).options(defer(Submission.answers)).filter(Submission.enrollment_id.in_(ids)).all()
    attempts=db.query(SubmissionAttempt).options(defer(SubmissionAttempt.answers)).join(Submission,SubmissionAttempt.submission_id==Submission.id).filter(Submission.enrollment_id.in_(ids)).all()
    grouped=defaultdict(dict)
    for sub in subs:
        grouped[sub.enrollment_id][sub.day_number]=sub
    published=defaultdict(set)
    for form in db.query(DayForm).join(DayFormVersion,DayFormVersion.day_form_id==DayForm.id).filter(DayFormVersion.questions != '[]'):
        published[form.bootcamp_id].add(form.day_number)
    for binding in db.query(EnrollmentDay).filter(EnrollmentDay.enrollment_id.in_(ids)):
        enrollment=by_id.get(binding.enrollment_id)
        if enrollment:
            published[enrollment.bootcamp_id].add(binding.day_number)
    return enrollments,camps,users,subs,attempts,grouped,published


def record_eligibility(db, enrollment_id, submitted=False):
    statement=insert(ParticipationDay).values(enrollment_id=enrollment_id,date=local_date(),eligible=True,submitted=submitted)
    db.execute(statement.on_conflict_do_update(index_elements=['enrollment_id','date'],set_={
        'eligible':True,'submitted':ParticipationDay.submitted | submitted}))


def capture(db, heartbeat=False):
    stamp=now()
    enrollments,camps,users,subs,attempts,grouped,published=load_data(db)
    for enrollment in enrollments:
        if enrollment.bootcamp_id not in camps:
            continue
        items=states(enrollment,camps[enrollment.bootcamp_id],grouped[enrollment.id],published[enrollment.bootcamp_id])
        if any(x['actionable'] for x in items):
            record_eligibility(db,enrollment.id)
    if heartbeat:
        coverage=db.get(MetricsCoverage,local_date())
        if not coverage:
            coverage=MetricsCoverage(date=local_date(),first_scan=stamp,last_scan=stamp,has_gap=False)
            db.add(coverage)
        else:
            coverage.has_gap=coverage.has_gap or stamp-coverage.last_scan > timedelta(minutes=10)
            coverage.last_scan=stamp


def statistics(db, camp_id=None, batch_id=None, start=None, end=None):
    end=end or local_date()
    start=start or end-timedelta(days=29)
    enrollments,camps,users,subs,attempts,grouped,published=load_data(db,camp_id,batch_id)
    ids={e.id for e in enrollments}
    enrol_by_id={e.id:e for e in enrollments}
    sub_by_id={s.id:s for s in subs}
    last_by_enrollment={}
    for attempt in attempts:
        eid=sub_by_id[attempt.submission_id].enrollment_id
        last_by_enrollment[eid]=max(last_by_enrollment.get(eid,attempt.submitted_at),attempt.submitted_at)
    actionable_users=set()
    current={s.current_attempt_id for s in subs}
    pending=[a for a in attempts if a.id in current and a.review_status=='pending']
    active_assignments={a.attempt_id for a in db.query(ReviewAssignment).filter_by(status='pending')}
    stamp=now()
    waits=[max(0,(stamp-a.submitted_at).total_seconds()/3600) for a in pending]
    reviewed=[a for a in attempts if a.reviewed_at and start<=local_date(a.reviewed_at)<=end]
    durations=sorted(max(0,(a.reviewed_at-a.submitted_at).total_seconds()/3600) for a in reviewed)
    followup=[]
    distribution=Counter()
    completed=0
    enrollment_progress=[]
    for enrollment in enrollments:
        camp=camps[enrollment.bootcamp_id]
        items=states(enrollment,camp,grouped[enrollment.id],published[camp.id])
        passed=sum(x['status']=='approved' for x in items)
        completed+=passed==camp.days
        enrollment_progress.append(dict(enrollment_id=enrollment.id,approved_days=passed,total_days=camp.days,completion_rate=round(passed/camp.days*100,1)))
        next_item=next((x for x in items if x['status']!='approved'),None)
        if next_item:
            category='等待审核' if next_item['status']=='pending' else '需修改' if next_item['status']=='rejected' else '未提交'
            distribution[(next_item['day'],category)]+=1
        actionable=next((x for x in items if x['actionable']),None)
        if actionable:
            actionable_users.add(enrollment.user_id)
        last=last_by_enrollment.get(enrollment.id)
        baseline=local_date(last) if last else enrollment.start_date
        if actionable and baseline and (local_date()-baseline).days>=3:
            followup.append(dict(enrollment_id=enrollment.id,nickname=users[enrollment.user_id].nickname,
                                 last_submitted_at=last.isoformat() if last else None,next_day=actionable['day']))
    records=db.query(ParticipationDay).filter(ParticipationDay.enrollment_id.in_(ids),ParticipationDay.date>=start,ParticipationDay.date<=end).all()
    day_counts=defaultdict(lambda:[set(),set()])
    for record in records:
        uid=enrol_by_id[record.enrollment_id].user_id
        if record.eligible: day_counts[record.date][0].add(uid)
        if record.submitted: day_counts[record.date][1].add(uid)
    day_counts[local_date()][0].update(actionable_users)
    coverage={c.date:c for c in db.query(MetricsCoverage).filter(MetricsCoverage.date>=start,MetricsCoverage.date<=end)}
    daily=[]
    day=start
    while day<=end:
        c=coverage.get(day)
        # A historical day is trustworthy only when the independent worker covered its full span.
        full=bool(c and not c.has_gap and local_date(c.first_scan)==day and
                  (c.first_scan+timedelta(hours=8)).time().hour==0 and (c.first_scan+timedelta(hours=8)).time().minute<=10 and
                  (c.last_scan+timedelta(hours=8)).time().hour==23 and (c.last_scan+timedelta(hours=8)).time().minute>=50)
        eligible,submitted=map(len,day_counts[day])
        known=full or day==local_date()
        daily.append(dict(date=day.isoformat(),eligible=eligible if known else None,submitted=submitted if known else None,
                          rate=round(submitted/eligible*100,1) if known and eligible else None,
                          coverage='complete' if full else 'partial' if day==local_date() else 'unavailable'))
        day+=timedelta(days=1)
    return dict(enrolled=len(enrollments),completed=completed,completion_rate=round(completed/len(enrollments)*100,1) if enrollments else 0,
                pending=len(pending),unclaimed=sum(a.id not in active_assignments for a in pending),overdue=sum(w>48 for w in waits),
                longest_wait_hours=round(max(waits,default=0),1),median_review_hours=round(median(durations),1) if durations else None,
                p90_review_hours=round(durations[math.ceil(len(durations)*.9)-1],1) if durations else None,
                daily=daily,followup=followup,enrollment_progress=enrollment_progress,
                distribution=[dict(day=day,status=kind,count=count) for (day,kind),count in sorted(distribution.items())],
                start=start.isoformat(),end=end.isoformat())
