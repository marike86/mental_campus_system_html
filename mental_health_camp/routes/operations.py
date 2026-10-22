import csv
import io
from datetime import date
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from auth import require_admin
from database import get_db
from models.bootcamp import Bootcamp
from models.batch import Batch
from services.metrics import statistics
from templates_config import templates

router=APIRouter(tags=['operations'])


def filtered(db, camp, batch, start, end):
    try:
        camp,batch=(int(camp) if camp else None),(int(batch) if batch else None)
    except ValueError:
        raise HTTPException(400,'筛选参数无效')
    if camp and not db.get(Bootcamp,camp):
        raise HTTPException(404,'训练营不存在')
    if batch:
        selected=db.get(Batch,batch)
        if not selected or camp and selected.bootcamp_id!=camp:
            raise HTTPException(400,'批次筛选无效')
    from services.clock import local_date
    from datetime import timedelta
    end=end or local_date()
    start=start or end-timedelta(days=29)
    if start>end or (end-start).days>365 or end>local_date():
        raise HTTPException(400,'日期范围须为过去 366 天内的有效区间')
    return statistics(db,camp,batch,start,end)


@router.get('/admin/operations')
async def page(request: Request,camp: str='',batch: str='',start: date=None,end: date=None,admin=Depends(require_admin),db: Session=Depends(get_db)):
    return templates.TemplateResponse('admin/operations.html',dict(request=request,user=admin,data=filtered(db,camp,batch,start,end),
        camps=db.query(Bootcamp).all(),batches=db.query(Batch).all()))


@router.get('/admin/api/operations')
async def api(camp: str='',batch: str='',start: date=None,end: date=None,admin=Depends(require_admin),db: Session=Depends(get_db)):
    return filtered(db,camp,batch,start,end)


@router.get('/admin/operations/export')
async def export(camp: str='',batch: str='',start: date=None,end: date=None,admin=Depends(require_admin),db: Session=Depends(get_db)):
    data=filtered(db,camp,batch,start,end)
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(['指标','数值'])
    for key in ['enrolled','completed','completion_rate','pending','unclaimed','overdue','longest_wait_hours','median_review_hours','p90_review_hours']:
        writer.writerow([key,data[key] if data[key] is not None else '暂无数据'])
    writer.writerow([])
    writer.writerow(['日期','有可做任务人数','提交人数','参与率','采集状态'])
    for day in data['daily']:
        writer.writerow([day['date'],day['eligible'],day['submitted'],day['rate'],day['coverage']])
    return StreamingResponse(iter([output.getvalue().encode('utf-8-sig')]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=operations.csv'})
