from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from auth import get_current_user, verify_csrf
from database import get_db
from models.workflow import Notification
from services.clock import now
from services.inbox import present
from templates_config import templates

router = APIRouter(prefix='/user', tags=['inbox'])


@router.get('/notifications')
async def inbox(request: Request, unread: bool=False, page: int=1, user=Depends(get_current_user), db: Session=Depends(get_db)):
    if page<1:
        raise HTTPException(400, '页码无效')
    query = db.query(Notification).filter_by(user_id=user.id)
    if unread:
        query = query.filter(Notification.read_at.is_(None))
    total = query.count()
    records = query.order_by(Notification.id.desc()).offset((page-1)*20).limit(20).all()
    return templates.TemplateResponse('user/notifications.html',dict(request=request,user=user,items=[present(db,n,user) for n in records],
                                                                    page=page,total=total,unread=unread))


@router.get('/api/notifications/unread-count')
async def unread_count(user=Depends(get_current_user), db: Session=Depends(get_db)):
    return dict(count=db.query(Notification).filter_by(user_id=user.id,read_at=None).count())


@router.post('/notifications/read-all')
async def read_all(user=Depends(get_current_user), db: Session=Depends(get_db), csrf=Depends(verify_csrf)):
    db.query(Notification).filter_by(user_id=user.id,read_at=None).update(dict(read_at=now()),synchronize_session=False)
    db.commit()
    return RedirectResponse('/user/notifications',303)


@router.post('/notifications/{notification_id}/read')
async def read_one(notification_id: int, user=Depends(get_current_user), db: Session=Depends(get_db), csrf=Depends(verify_csrf)):
    item = db.query(Notification).filter_by(id=notification_id,user_id=user.id).first()
    if not item:
        raise HTTPException(404, '通知不存在')
    if item.read_at is None:
        item.read_at=now()
        db.commit()
    return RedirectResponse('/user/notifications',303)
