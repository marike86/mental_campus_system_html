import uuid
import pytest
from fastapi import HTTPException
from test_workflows import world
from models.audit_log import AuditLog, BulkOperation
from models.enrollment import Enrollment
from services import bulk


def test_approval_atomic_replay_and_audit(world):
    w=world;w.enrollment.status='pending';w.db.commit()
    data=bulk.preview(w.db,w.admin,'approve',[w.enrollment.id])
    request_id=str(uuid.uuid4())
    result=bulk.execute(w.db,w.admin,data['token'],request_id)
    assert w.enrollment.status=='approved'
    assert bulk.execute(w.db,w.admin,data['token'],request_id)==result
    assert w.db.query(BulkOperation).count()==1
    assert w.db.query(AuditLog).filter_by(operation_id=request_id).count()==2


def test_changed_preview_and_wrong_actor(world):
    w=world;w.enrollment.status='pending';w.db.commit()
    data=bulk.preview(w.db,w.admin,'approve',[w.enrollment.id])
    with pytest.raises(HTTPException) as error:
        bulk.execute(w.db,w.super_admin,data['token'],str(uuid.uuid4()))
    assert error.value.status_code==403
    w.enrollment.status='rejected';w.db.commit()
    with pytest.raises(HTTPException) as error:
        bulk.execute(w.db,w.admin,data['token'],str(uuid.uuid4()))
    w.db.rollback()
    assert error.value.status_code==409
    assert w.db.query(BulkOperation).count()==0


def test_invalid_lists_and_tamper(world):
    w=world
    for ids in ([],[1,1],list(range(1,102))):
        with pytest.raises(HTTPException): bulk.preview(w.db,w.admin,'approve',ids)
    with pytest.raises(HTTPException): bulk.execute(w.db,w.admin,'invalid',str(uuid.uuid4()))


def test_assignment_transfer_and_atomic_audit_failure(world,monkeypatch):
    from services import courses,reviews
    from services.versions import bound_version
    from starlette.datastructures import FormData
    w=world
    courses.start(w.db,w.enrollment,1)
    version=bound_version(w.db,w.enrollment.id,1)
    sub=courses.submit(w.db,w.enrollment,1,FormData({'version_id':str(version.id),'q_answer':'test','q_scale':'0'}))
    w.db.commit()
    data=bulk.preview(w.db,w.admin,'assign',[sub.id],w.reviewer.id)
    bulk.execute(w.db,w.admin,data['token'],str(uuid.uuid4()))
    old=reviews.active_assignment(w.db,sub.current_attempt_id)
    data=bulk.preview(w.db,w.admin,'transfer',[sub.id],w.other.id)
    bulk.execute(w.db,w.admin,data['token'],str(uuid.uuid4()))
    w.db.refresh(old)
    assert old.status=='transferred'
    with pytest.raises(HTTPException): reviews.authorize_detail(w.db,sub,w.db.get(__import__('models.workflow',fromlist=['SubmissionAttempt']).SubmissionAttempt,sub.current_attempt_id),w.reviewer)
    w.db.rollback()
    w.enrollment.status='pending';w.db.commit()
    data=bulk.preview(w.db,w.admin,'approve',[w.enrollment.id])
    def fail(*a,**k): raise RuntimeError('log failure')
    monkeypatch.setattr(bulk,'record',fail)
    with pytest.raises(RuntimeError): bulk.execute(w.db,w.admin,data['token'],str(uuid.uuid4()))
    w.db.rollback();w.db.refresh(w.enrollment)
    assert w.enrollment.status=='pending'


def test_expiry_disabled_camp_and_capacity(world):
    from jose import jwt
    from config import SECRET_KEY
    w=world;w.enrollment.status='pending';w.db.commit()
    data=bulk.preview(w.db,w.admin,'approve',[w.enrollment.id])
    payload=jwt.decode(data['token'],SECRET_KEY,algorithms=['HS256']);payload['exp']=1
    expired=jwt.encode(payload,SECRET_KEY,algorithm='HS256')
    with pytest.raises(HTTPException) as error: bulk.execute(w.db,w.admin,expired,str(uuid.uuid4()))
    w.db.rollback();assert error.value.status_code==409
    w.camp.is_active=False;w.db.commit()
    with pytest.raises(HTTPException): bulk.preview(w.db,w.admin,'approve',[w.enrollment.id])
    w.reviewer.max_concurrent_tasks=0;w.db.commit()
    with pytest.raises(HTTPException): bulk.preview(w.db,w.admin,'assign',[1],w.reviewer.id)


def test_csrf_permissions_and_export(world):
    from test_workflows import login
    from auth import verify_csrf
    import tests as helpers
    w=world;login(w,w.user)
    assert w.client.post('/admin/bulk/preview',json={'action':'approve','ids':[w.enrollment.id]}).status_code==403
    login(w,w.admin)
    old=helpers.app.dependency_overrides.pop(verify_csrf,None)
    try:
        assert w.client.post('/admin/bulk/preview',json={'action':'approve','ids':[w.enrollment.id]}).status_code==403
    finally:
        if old: helpers.app.dependency_overrides[verify_csrf]=old
    response=w.client.get('/admin/operations/followup/export')
    assert response.status_code==200
    assert response.content.startswith(b'\xef\xbb\xbf')
    assert '联系方式' not in response.text


def test_independent_connections_compete_for_same_batch(world):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import tests as helpers
    from models.user import User
    w=world;w.enrollment.status='pending';w.db.commit()
    data=bulk.preview(w.db,w.admin,'approve',[w.enrollment.id]);actor_id=w.admin.id
    barrier=Barrier(2)
    def run(_):
        with helpers.SessionLocal() as db:
            actor=db.get(User,actor_id);barrier.wait()
            try:
                bulk.execute(db,actor,data['token'],str(uuid.uuid4()));return 200
            except HTTPException as exc:
                db.rollback();return exc.status_code
    with ThreadPoolExecutor(2) as pool: results=list(pool.map(run,range(2)))
    assert sorted(results)==[200,409]
    assert w.db.query(BulkOperation).count()==1
