from fastapi import APIRouter, Depends, Request, HTTPException
from auth import require_admin, verify_csrf
from database import get_db
from services import bulk
router=APIRouter()

@router.post('/admin/bulk/preview')
async def preview(request:Request,actor=Depends(require_admin),db=Depends(get_db),csrf=Depends(verify_csrf)):
    try: data=await request.json()
    except ValueError: raise HTTPException(400,"请求JSON无效")
    if not isinstance(data,dict): raise HTTPException(400,"请求格式无效")
    return bulk.preview(db,actor,data.get('action'),data.get('ids'),data.get('reviewer_id'))

@router.post('/admin/bulk/execute')
async def execute(request:Request,actor=Depends(require_admin),db=Depends(get_db),csrf=Depends(verify_csrf)):
    try: data=await request.json()
    except ValueError: raise HTTPException(400,"请求JSON无效")
    if not isinstance(data,dict): raise HTTPException(400,"请求格式无效")
    try: return bulk.execute(db,actor,data.get('token'),data.get('request_id'))
    except Exception:
        db.rollback()
        raise

from models.enrollment import Enrollment
from models.bootcamp import Bootcamp
from templates_config import templates
@router.get('/admin/enrollments')
async def enrollments(request:Request,page:int=1,actor=Depends(require_admin),db=Depends(get_db)):
    if page<1: raise HTTPException(400,'页码无效')
    query=db.query(Enrollment).filter_by(status='pending')
    return templates.TemplateResponse('admin/enrollments.html',dict(request=request,user=actor,records=query.order_by(Enrollment.id).offset((page-1)*20).limit(20).all(),page=page,total=query.count()))
