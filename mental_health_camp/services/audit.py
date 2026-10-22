import hashlib
from models.audit_log import AuditLog
from models.user import User
from services.clock import now

EVENTS = {"创建训练营":"camp.create", "更新训练营":"camp.update", "创建批次":"batch.create", "编辑批次":"batch.update", "删除批次":"batch.delete", "创建用户":"account.create", "创建审核员":"account.create_reviewer", "删除用户":"account.delete", "审批通过加入申请":"enrollment.approve", "拒绝加入申请":"enrollment.reject", "导出数据":"export.generated"}

def record(db, actor_id, action, target_type, target_id=None, detail=None, *, event_type=None, operation_id=None, camp_id=None, batch_id=None):
    actor=db.get(User,actor_id)
    # Only explicitly approved metadata is retained.
    safe={k:v for k,v in (detail or {}).items() if k in {'status','before','after','version','attempt_id','reviewer_id','assignment_id','count','batch_id','bootcamp_id','role','enrollment_count','deleted','released'}}
    if camp_id is None:
        if target_type=='bootcamp': camp_id=target_id
        elif target_type=='enrollment':
            from models.enrollment import Enrollment
            target=db.get(Enrollment,target_id)
            if target: camp_id,batch_id=target.bootcamp_id,target.batch_id
        elif target_type=='batch':
            from models.batch import Batch
            target=db.get(Batch,target_id)
            if target: camp_id,batch_id=target.bootcamp_id,target.id
        elif target_type=='submission':
            from models.submission import Submission
            from models.enrollment import Enrollment
            sub=db.get(Submission,target_id)
            target=db.get(Enrollment,sub.enrollment_id) if sub else None
            if target: camp_id,batch_id=target.bootcamp_id,target.batch_id
    types={'user':'users','bootcamp':'bootcamps','batch':'batches','enrollment':'enrollments','submission':'submissions'}
    for obj,changes in db.info.get('audit_changes',{}).values():
        if getattr(obj,'__tablename__',None)==types.get(target_type) and getattr(obj,'id',None)==target_id:
            safe['changes']=changes
    item=AuditLog(admin_id=actor_id,action=action,target_type=target_type,target_id=target_id,detail=safe,event_type=event_type or EVENTS.get(action,target_type+'.'+hashlib.sha256(action.encode()).hexdigest()[:12]),actor_role=actor.role if actor else None,operation_id=operation_id,camp_id=camp_id,batch_id=batch_id,created_at=now())
    db.add(item)
    db.flush()
    return item


# Capture only operational fields before callers flush; never capture answers or credentials.
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session
SAFE_FIELDS={'status','is_active','days','start_date','end_date','batch_id','reviewer_id','max_concurrent_tasks','role'}
@event.listens_for(Session,'before_flush')
def capture_changes(session,flush_context,instances):
    changes=session.info.setdefault('audit_changes',{})
    for obj in session.dirty:
        if isinstance(obj,AuditLog): continue
        selected={}
        state=inspect(obj)
        for key in SAFE_FIELDS.intersection(state.attrs.keys()):
            history=state.attrs[key].history
            if history.has_changes():
                selected[key]={'before':str(history.deleted[0]) if history.deleted else None,'after':str(history.added[0]) if history.added else None}
        if selected: changes[id(obj)]=(obj,selected)

@event.listens_for(Session,'after_commit')
@event.listens_for(Session,'after_rollback')
def clear_changes(session):
    session.info.pop('audit_changes',None)
