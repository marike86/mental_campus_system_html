import hashlib
import json
import uuid
from datetime import datetime, timedelta
from jose import jwt, JWTError
from fastapi import HTTPException
from config import SECRET_KEY
from models.audit_log import BulkOperation
from models.enrollment import Enrollment
from models.bootcamp import Bootcamp
from models.batch import Batch
from models.user import User
from services.clock import now, local_date
from services.versions import write_lock
from services import reviews
from services.audit import record


def validate(db, action, ids, reviewer_id):
    if action not in ('approve','assign','transfer') or not isinstance(ids,list) or not 1<=len(ids)<=100 or any(type(i)!=int or i<1 for i in ids) or len(set(ids))!=len(ids):
        raise HTTPException(400,'操作或记录列表无效，最多100条且不得重复')
    snapshots=[]; conflicts=[]
    reviewer=None
    if action!='approve':
        reviewer=db.get(User,reviewer_id) if type(reviewer_id)==int else None
        if not reviewer or reviewer.role!='reviewer' or not reviewer.is_active:
            raise HTTPException(409,dict(message='审核员不可用，整批未执行',records=ids))
        from models.review_assignment import ReviewAssignment
        used=db.query(ReviewAssignment).filter_by(reviewer_id=reviewer.id,status='pending').count()
        if used+len(ids)>reviewer.max_concurrent_tasks:
            raise HTTPException(409,dict(message='审核员容量不足，整批未执行',records=ids))
    for identifier in ids:
        if action=='approve':
            e=db.query(Enrollment).populate_existing().filter_by(id=identifier).first()
            camp=db.get(Bootcamp,e.bootcamp_id) if e else None
            batch=db.get(Batch,e.batch_id) if e and e.batch_id else None
            if not e or e.status!='pending' or not camp or not camp.is_active or e.batch_id and (not batch or not batch.is_active or batch.bootcamp_id!=camp.id):
                conflicts.append(identifier); continue
            snapshots.append(dict(id=e.id,status=e.status,camp=e.bootcamp_id,batch=e.batch_id,start=str(e.start_date),batch_start=str(batch.start_date) if batch else None))
        else:
            try: sub,attempt=reviews.current_attempt(db,identifier)
            except HTTPException: conflicts.append(identifier); continue
            assignment=reviews.active_assignment(db,attempt.id)
            if attempt.review_status!='pending' or action=='assign' and assignment or action=='transfer' and (not assignment or assignment.reviewer_id==reviewer_id):
                conflicts.append(identifier); continue
            snapshots.append(dict(id=sub.id,attempt=attempt.id,assignment=assignment.id if assignment else None,reviewer=assignment.reviewer_id if assignment else None))
    if conflicts: raise HTTPException(409,dict(message='记录状态冲突，整批未执行',records=conflicts))
    return snapshots


def preview(db,actor,action,ids,reviewer_id=None):
    snapshot=validate(db,action,ids,reviewer_id)
    payload=dict(actor=actor.id,action=action,ids=ids,reviewer_id=reviewer_id,snapshot=snapshot,exp=now()+timedelta(minutes=10),nonce=str(uuid.uuid4()))
    capacity=None
    if action!='approve':
        from models.review_assignment import ReviewAssignment
        reviewer=db.get(User,reviewer_id)
        used=db.query(ReviewAssignment).filter_by(reviewer_id=reviewer_id,status='pending').count()
        capacity=dict(limit=reviewer.max_concurrent_tasks,before=used,after=used+len(ids))
    return dict(request_id=payload["nonce"],records=snapshot,count=len(ids),reviewer_id=reviewer_id,capacity=capacity,token=jwt.encode(payload,SECRET_KEY,algorithm='HS256'))


def execute(db,actor,token,request_id):
    try:
        uuid.UUID(request_id)
        payload=jwt.decode(token,SECRET_KEY,algorithms=['HS256'],options={'verify_exp':False})
    except (JWTError,ValueError,TypeError,AttributeError): raise HTTPException(400,'确认凭据无效')
    if payload.get('actor')!=actor.id: raise HTTPException(403,'确认凭据不属于当前管理员')
    digest=hashlib.sha256(token.encode()).hexdigest()
    write_lock(db)
    previous=db.get(BulkOperation,request_id)
    if previous:
        if previous.actor_id!=actor.id or previous.fingerprint!=digest: raise HTTPException(409,'请求编号已被使用')
        return previous.result
    if payload['exp']<datetime.now().timestamp(): raise HTTPException(409,'预览已过期，请重新预览')
    snapshot=validate(db,payload['action'],payload['ids'],payload['reviewer_id'])
    if snapshot!=payload['snapshot']: raise HTTPException(409,dict(message='预览后记录已变更，整批未执行',records=payload['ids']))
    for item in snapshot:
        if payload['action']=='approve':
            e=db.get(Enrollment,item['id']); before=e.status
            batch=db.get(Batch,e.batch_id) if e.batch_id else None
            e.status='approved'; e.start_date=e.start_date or (batch.start_date if batch else None) or local_date()
            record(db,actor.id,'批准报名','enrollment',e.id,{'before':before,'after':e.status},event_type='enrollment.approve',operation_id=request_id,camp_id=e.bootcamp_id,batch_id=e.batch_id)
        else:
            assignment=reviews.assign(db,item['id'],payload['reviewer_id'],actor,item['attempt'],operation_id=request_id)
    if payload['action']=='approve':
        from services.metrics import capture
        capture(db)
    result=dict(operation_id=request_id,count=len(snapshot),action=payload['action'])
    record(db,actor.id,'批量操作完成','bulk',detail={'count':len(snapshot)},event_type='bulk.'+payload['action'],operation_id=request_id)
    db.add(BulkOperation(request_id=request_id,actor_id=actor.id,fingerprint=digest,result=result))
    db.commit()
    return result
