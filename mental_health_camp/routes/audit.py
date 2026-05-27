from datetime import datetime
from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from models.audit_log import AuditLog
from auth import require_admin
from config import APP_NAME, ITEMS_PER_PAGE
from templates_config import templates

router = APIRouter(tags=["audit"])


def log_admin_action(db: Session, admin_id: int, action: str, target_type: str, target_id: int = None, detail: dict = None):
    log = AuditLog(
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    )
    db.add(log)
    db.commit()


@router.get("/admin/audit")
async def audit_log_page(request: Request, page: int = 1, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    total = db.query(AuditLog).count()
    total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * ITEMS_PER_PAGE
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).offset(offset).limit(ITEMS_PER_PAGE).all()
    admin_ids = {l.admin_id for l in logs}
    admin_map = {}
    for uid in admin_ids:
        u = db.query(User).filter(User.id == uid).first()
        if u:
            admin_map[uid] = u.nickname
    return templates.TemplateResponse("admin/audit.html", {
        "request": request, "user": admin, "app_name": APP_NAME,
        "logs": logs, "admin_map": admin_map,
        "page": page, "total_pages": total_pages, "total": total,
    })
