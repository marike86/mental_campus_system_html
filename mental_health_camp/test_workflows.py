from datetime import timedelta
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import threading
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from fastapi import HTTPException
from starlette.datastructures import FormData
from fastapi.testclient import TestClient
from sqlalchemy import text
import tests as helpers
from auth import create_access_token, verify_csrf, get_password_hash
from models.user import User
from models.bootcamp import Bootcamp
from models.enrollment import Enrollment
from models.day_form import DayForm
from models.submission import Submission
from models.review_assignment import ReviewAssignment
from models.workflow import WorkflowSchema, DayFormVersion, EnrollmentDay, SubmissionAttempt, Notification, ParticipationDay
from services import courses, reviews, metrics
from services.versions import publish
from services.clock import now, local_date
from services.inbox import overdue_scan
from utils.crypto import decrypt_data

HASH=get_password_hash('Testing123')
QUESTIONS=[dict(id='answer',type='text',label='感受',required=True),dict(id='scale',type='likert',label='评分',min=0,max=5,required=True)]


@pytest.fixture
def world():
    helpers._setup_db()
    db=helpers.SessionLocal()
    db.add(WorkflowSchema(id=1,version=2,installed_at=now()))
    people=[]
    for index,role in enumerate(['admin','user','reviewer','reviewer','super_admin']):
        person=User(email=f'{index}@example.com',nickname=f'角色{index}',role=role,hashed_password=HASH,is_active=True,max_concurrent_tasks=1)
        db.add(person)
        people.append(person)
    db.flush()
    admin,user,reviewer,other,super_admin=people
    camp=Bootcamp(name='测试课程',days=2,is_active=True,created_by=admin.id)
    db.add(camp);db.flush()
    forms=[]
    for day in (1,2):
        form=DayForm(bootcamp_id=camp.id,day_number=day,questions=QUESTIONS)
        db.add(form);db.flush();publish(db,form,admin.id);forms.append(form)
    enrollment=Enrollment(user_id=user.id,bootcamp_id=camp.id,start_date=local_date()-timedelta(days=2),status='approved')
    db.add(enrollment);db.commit()
    client=TestClient(helpers.app)
    yield SimpleNamespace(db=db,admin=admin,user=user,reviewer=reviewer,other=other,super_admin=super_admin,camp=camp,forms=forms,enrollment=enrollment,client=client)
    client.close();db.close()


def login(w,person):
    w.client.cookies.clear()
    w.client.cookies.set('access_token',create_access_token({'sub':person.id}))


def submit(w,day=1,answer='记录',score='0'):
    version=courses.start(w.db,w.enrollment,day)
    sub=courses.submit(w.db,w.enrollment,day,FormData(dict(version_id=str(version.id),q_answer=answer,q_scale=score)))
    w.db.commit()
    return sub


def test_full_flow_http_and_immutable_rounds(world):
    w=world;login(w,w.user)
    url=f'/user/form/{w.enrollment.id}/1'
    assert '开始学习' in w.client.get(url).text
    assert w.client.post(f'/user/course/{w.enrollment.id}/1/start',follow_redirects=False).status_code==303
    w.db.expire_all()
    version=courses.bound_version(w.db,w.enrollment.id,1)
    response=w.client.post(url,data=dict(version_id=version.id,q_answer='第一次',q_scale='0'),follow_redirects=False)
    assert response.status_code==303
    w.db.expire_all();sub=w.db.query(Submission).one();first=sub.current_attempt_id
    login(w,w.reviewer)
    assert w.client.get(f'/review/{sub.id}').status_code==403
    assert '第一次' not in w.client.get('/review/pending').text
    assert w.client.post(f'/review/{sub.id}/claim',data=dict(attempt_id=first),follow_redirects=False).status_code==303
    assert '第一次' in w.client.get(f'/review/{sub.id}').text
    assert w.client.post(f'/review/{sub.id}/reject',data=dict(attempt_id=first,comment='请补充细节'),follow_redirects=False).status_code==303
    login(w,w.user)
    assert '请补充细节' in w.client.get('/user/notifications').text
    assert '修改后重提' in w.client.get('/user/notifications').text
    assert '第一次' in w.client.get(url).text
    response=w.client.post(url,data=dict(version_id=version.id,q_answer='第二次',q_scale=2),follow_redirects=False)
    assert response.status_code==303
    assert '修改后重提' not in w.client.get('/user/notifications').text
    w.db.expire_all();sub=w.db.query(Submission).one();second=sub.current_attempt_id
    assert first!=second
    assert decrypt_data(w.db.get(SubmissionAttempt,first).answers)['answer']=='第一次'
    login(w,w.reviewer)
    assert '第 1 次' in w.client.get('/review/pending?view=completed').text
    w.client.post(f'/review/{sub.id}/claim',data=dict(attempt_id=second))
    assert w.client.post(f'/review/{sub.id}/approve',data=dict(attempt_id=first),follow_redirects=False).status_code==409
    assert w.client.post(f'/review/{sub.id}/approve',data=dict(attempt_id=second),follow_redirects=False).status_code==303
    assert w.client.post(f'/review/{sub.id}/reject',data=dict(attempt_id=second,comment='改判'),follow_redirects=False).status_code==409
    login(w,w.user)
    data=w.client.get(f'/user/api/progress/{w.enrollment.id}').json()
    assert data['days'][0]['status']=='approved' and data['days'][1]['actionable']
    history=w.client.get(f'/user/history/{w.enrollment.id}').text
    assert '第一次' in history and '第二次' in history and '请补充细节' in history


def test_version_pinning_and_export(world):
    w=world;sub=submit(w)
    old=courses.bound_version(w.db,w.enrollment.id,1)
    w.forms[0].questions=[dict(id='new',type='text',label='新题目')]
    publish(w.db,w.forms[0],w.admin.id);w.db.commit()
    assert courses.bound_version(w.db,w.enrollment.id,1).id==old.id
    second=User(email='second@example.com',nickname='第二学员',role='user',hashed_password=HASH)
    w.db.add(second);w.db.flush()
    e=Enrollment(user_id=second.id,bootcamp_id=w.camp.id,start_date=local_date(),status='approved')
    w.db.add(e);w.db.flush()
    assert courses.start(w.db,e,1).id!=old.id
    w.db.commit();login(w,w.admin)
    response=w.client.post('/admin/export',data=dict(bootcamp_id=w.camp.id))
    assert response.status_code==200
    assert '感受' in response.text and '新题目' not in response.text
    assert '版本号' in response.text and '提交轮次' in response.text


@pytest.mark.parametrize('field,value,expected',[('start_date','future','future'),('status','pending','available'),('active',False,'available')])
def test_blocking_reasons(world,field,value,expected):
    w=world
    if field=='start_date':w.enrollment.start_date=local_date()+timedelta(days=1)
    elif field=='active':w.camp.is_active=value
    else:w.enrollment.status=value
    w.db.commit()
    _,items=courses.progress(w.db,w.enrollment)
    assert not items[0]['actionable'] and items[0]['reason']
    with pytest.raises(HTTPException):courses.start(w.db,w.enrollment,1)


def test_dual_unlock_makeup_and_missing_version(world):
    w=world
    with pytest.raises(HTTPException):courses.start(w.db,w.enrollment,2)
    version=courses.start(w.db,w.enrollment,1)
    with pytest.raises(HTTPException):courses.submit(w.db,w.enrollment,1,FormData(dict(q_answer='绕过',q_scale='1')))
    sub=submit(w)
    reviews.decide(w.db,sub.id,sub.current_attempt_id,w.admin,'approved');w.db.commit()
    w.enrollment.start_date=local_date();w.db.commit()
    with pytest.raises(HTTPException):courses.start(w.db,w.enrollment,2)
    w.enrollment.start_date=local_date()-timedelta(days=10);w.db.commit()
    assert courses.start(w.db,w.enrollment,2)


def test_failed_resubmit_and_rollback(world):
    w=world;sub=submit(w)
    reviews.decide(w.db,sub.id,sub.current_attempt_id,w.admin,'rejected','补充');w.db.commit()
    old=sub.current_attempt_id
    with pytest.raises(HTTPException):submit(w,answer='',score='bad')
    w.db.rollback();w.db.refresh(sub)
    assert sub.current_attempt_id==old and sub.review_status=='rejected'
    assert w.db.query(SubmissionAttempt).count()==1
    new=submit(w)
    reviews.decide(w.db,new.id,new.current_attempt_id,w.admin,'approved');w.db.rollback();w.db.refresh(new)
    assert new.review_status=='pending'
    assert w.db.query(Notification).count()==1


def test_transfer_capacity_disable_and_permissions(world):
    w=world;sub=submit(w)
    reviews.assign(w.db,sub.id,w.reviewer.id,w.reviewer,sub.current_attempt_id);w.db.commit()
    with pytest.raises(HTTPException):reviews.decide(w.db,sub.id,sub.current_attempt_id,w.other,'approved')
    reviews.assign(w.db,sub.id,w.other.id,w.admin,sub.current_attempt_id);w.db.commit()
    with pytest.raises(HTTPException):reviews.decide(w.db,sub.id,sub.current_attempt_id,w.reviewer,'approved')
    w.db.rollback()
    login(w,w.admin)
    assert w.client.get('/super-admin/assignments',follow_redirects=False).status_code==303
    assert w.client.get('/super-admin/reviewers').status_code==403
    login(w,w.super_admin)
    assert w.client.post(f'/super-admin/reviewer/{w.other.id}/toggle',follow_redirects=False).status_code==302
    w.db.expire_all()
    assert not reviews.active_assignment(w.db,sub.current_attempt_id)
    assert w.db.get(Submission,sub.id).reviewer_id is None


def test_simultaneous_claims_only_one_wins(world):
    w=world;sub=submit(w);sid,aid=sub.id,sub.current_attempt_id;reviewers=[w.reviewer.id,w.other.id]
    w.db.commit()
    barrier=threading.Barrier(2)
    def claim(uid):
        with helpers.SessionLocal() as db:
            actor=db.get(User,uid)
            barrier.wait()
            try:
                reviews.assign(db,sid,uid,actor,aid);db.commit();return 200
            except HTTPException as exc:
                db.rollback();return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(claim,reviewers))
    assert sorted(results)==[200,409]
    assert w.db.query(ReviewAssignment).filter_by(status='pending').count()==1


def test_capacity_and_reject_comment(world):
    w=world;sub=submit(w)
    reviews.assign(w.db,sub.id,w.reviewer.id,w.reviewer,sub.current_attempt_id);w.db.commit()
    with pytest.raises(HTTPException):reviews.decide(w.db,sub.id,sub.current_attempt_id,w.reviewer,'rejected',' ')
    second=User(email='extra@example.com',nickname='另一人',role='user',hashed_password=HASH)
    w.db.add(second);w.db.flush()
    enrolled=Enrollment(user_id=second.id,bootcamp_id=w.camp.id,start_date=local_date(),status='approved')
    w.db.add(enrolled);w.db.flush()
    version=courses.start(w.db,enrolled,1)
    other=courses.submit(w.db,enrolled,1,FormData(dict(version_id=version.id,q_answer='另一人',q_scale='2')));w.db.commit()
    with pytest.raises(HTTPException):reviews.assign(w.db,other.id,w.reviewer.id,w.reviewer,other.current_attempt_id)


def test_inbox_ownership_csrf_and_overdue_dedupe(world):
    w=world;sub=submit(w)
    attempt=w.db.get(SubmissionAttempt,sub.current_attempt_id)
    attempt.submitted_at=now()-timedelta(hours=49);w.db.commit()
    overdue_scan(w.db);w.db.commit();count=w.db.query(Notification).count()
    overdue_scan(w.db);w.db.commit()
    assert count==w.db.query(Notification).count() and count==2
    reviews.decide(w.db,sub.id,attempt.id,w.admin,'rejected','请补充');w.db.commit()
    n=w.db.query(Notification).filter_by(user_id=w.user.id).one()
    login(w,w.reviewer)
    assert w.client.post(f'/user/notifications/{n.id}/read',follow_redirects=False).status_code==404
    login(w,w.user)
    saved=helpers.app.dependency_overrides.pop(verify_csrf)
    try:
        assert w.client.post(f'/user/notifications/{n.id}/read',follow_redirects=False).status_code==403
        w.client.get('/user/notifications')
        token=w.client.cookies.get('csrf_token')
        assert w.client.post(f'/user/notifications/{n.id}/read',data=dict(csrf_token=token),follow_redirects=False).status_code==303
    finally:helpers.app.dependency_overrides[verify_csrf]=saved


def test_metrics_pending_is_not_completed_and_legacy_unknown(world):
    w=world;sub=submit(w)
    data=metrics.statistics(w.db)
    assert data['completion_rate']==0 and data['pending']==1 and data['unclaimed']==1
    assert data['daily'][-1]['eligible']==1 and data['daily'][-1]['submitted']==1
    assert data['daily'][0]['coverage']=='unavailable'
    assert data['distribution'][0]['status']=='等待审核'
    assert not data['followup']
    login(w,w.admin)
    assert w.client.get('/admin/operations').status_code==200
    assert w.client.get('/admin/operations/export').status_code==200
    login(w,w.user)
    assert w.client.get('/admin/api/operations').status_code==403


def test_delete_user_removes_workflow_rows(world):
    w=world;sub=submit(w)
    reviews.decide(w.db,sub.id,sub.current_attempt_id,w.admin,'rejected','请补充');w.db.commit()
    login(w,w.admin)
    assert w.client.post('/admin/delete-user',data=dict(user_id=w.user.id,confirm='yes'),follow_redirects=False).status_code==302
    w.db.expire_all()
    for model in (Enrollment,EnrollmentDay,Submission,SubmissionAttempt,Notification,ParticipationDay):
        assert w.db.query(model).count()==0


def test_publish_validation_and_prohibit_shrinking(world):
    w=world;submit(w)
    login(w,w.admin)
    response=w.client.post(f'/admin/bootcamp/{w.camp.id}',data=dict(name='课程',days=1),follow_redirects=False)
    assert response.status_code==409
    w.forms[0].questions=QUESTIONS+QUESTIONS
    with pytest.raises(HTTPException):publish(w.db,w.forms[0],w.admin.id)


def test_empty_filter_values_and_reviewer_history_pages(world):
    w=world;sub=submit(w)
    reviews.assign(w.db,sub.id,w.reviewer.id,w.reviewer,sub.current_attempt_id)
    reviews.decide(w.db,sub.id,sub.current_attempt_id,w.reviewer,'rejected','建议');w.db.commit()
    login(w,w.super_admin)
    for url in ['/super-admin/reviewers',f'/super-admin/reviewer/{w.reviewer.id}','/super-admin/review-stats',
                '/review/pending?camp=&batch=','/admin/operations?camp=&batch=']:
        assert w.client.get(url).status_code==200,url


def test_metrics_overdue_durations_and_followup(world):
    w=world;sub=submit(w)
    attempt=w.db.get(SubmissionAttempt,sub.current_attempt_id)
    attempt.submitted_at=now()-timedelta(hours=60)
    sub.submitted_at=attempt.submitted_at
    w.db.commit()
    assert metrics.statistics(w.db)['overdue']==1
    reviews.decide(w.db,sub.id,attempt.id,w.admin,'approved');w.db.commit()
    data=metrics.statistics(w.db)
    assert data['pending']==0 and data['median_review_hours']>=60 and data['p90_review_hours']>=60
    assert data['completion_rate']==0  # Second day is not approved yet.
    attempt.submitted_at=now()-timedelta(days=4);w.db.commit()
    assert len(metrics.statistics(w.db)['followup'])==1


def test_normal_form_failure_preserves_entered_answer(world):
    w=world;login(w,w.user)
    w.client.post(f'/user/course/{w.enrollment.id}/1/start')
    w.db.expire_all();version=courses.bound_version(w.db,w.enrollment.id,1)
    response=w.client.post(f'/user/form/{w.enrollment.id}/1',data=dict(version_id=version.id,q_answer='保留我',q_scale='invalid'))
    assert response.status_code==400
    assert '保留我' in response.text and '量表答案必须为整数' in response.text
    assert w.db.query(Submission).count()==0
