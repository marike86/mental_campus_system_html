from datetime import datetime
from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from models.audit_log import AuditLog
from services.audit import record
from auth import require_admin
from config import APP_NAME, ITEMS_PER_PAGE
from templates_config import templates

router = APIRouter(tags=["audit"])


def log_admin_action(db: Session, admin_id: int, action: str, target_type: str, target_id: int = None, detail: dict = None):
    return record(db, admin_id, action, target_type, target_id, detail)



@router.get("/admin/audit")
async def audit_log_page(request: Request, page: int = 1, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    from datetime import timedelta, time
    from fastapi import HTTPException
    from services.clock import local_date
    query = db.query(AuditLog)
    try:
        start=datetime.fromisoformat(request.query_params.get('start', (local_date()-timedelta(days=29)).isoformat()))
        end=datetime.fromisoformat(request.query_params.get('end', local_date().isoformat()))+timedelta(days=1)
        if start>=end: raise ValueError()
        query=query.filter(AuditLog.created_at>=start-timedelta(hours=8),AuditLog.created_at<end-timedelta(hours=8))
        for key in ('admin_id','event_type','target_type','target_id','camp_id','batch_id','operation_id'):
            value=request.query_params.get(key)
            if value:
                if key in ('admin_id','target_id','camp_id','batch_id'): value=int(value)
                query=query.filter(getattr(AuditLog,key)==value)
    except ValueError:
        raise HTTPException(400, '筛选参数无效')
    total = query.count()
    total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * ITEMS_PER_PAGE
    logs = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(ITEMS_PER_PAGE).all()
    admin_ids = {l.admin_id for l in logs}
    admin_map = {}
    admin_map = {u.id:u.nickname for u in db.query(User).filter(User.id.in_(admin_ids))}
    return templates.TemplateResponse("admin/audit.html", {
        "request": request, "user": admin, "app_name": APP_NAME,
        "logs": logs, "admin_map": admin_map,
        "page": page, "total_pages": total_pages, "total": total,
    })
