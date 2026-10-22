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
    from services.audit import record
    record(db,admin.id,'生成运营统计导出','export',event_type='export.operations.generated',camp_id=int(camp) if camp else None,batch_id=int(batch) if batch else None)
    db.commit()
    return StreamingResponse(iter([output.getvalue().encode('utf-8-sig')]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=operations.csv'})

@router.get('/admin/operations/followup/export')
async def followup_export(camp:str='',batch:str='',admin=Depends(require_admin),db:Session=Depends(get_db)):
    from models.enrollment import Enrollment
    from models.submission import Submission
    from services.courses import states
    from services.audit import record
    from services.clock import local_date
    data=filtered(db,camp,batch,None,None)
    ids=[x['enrollment_id'] for x in data['followup']]
    enrollments={e.id:e for e in db.query(Enrollment).filter(Enrollment.id.in_(ids))}
    camps={c.id:c.name for c in db.query(Bootcamp)}
    batches={b.id:b.name for b in db.query(Batch)}
    subs={(s.enrollment_id,s.day_number):s.review_status for s in db.query(Submission).filter(Submission.enrollment_id.in_(ids))}
    def safe(value):
        value=str(value if value is not None else '')
        return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
    output=io.StringIO();writer=csv.writer(output)
    writer.writerow(['学员ID','昵称','报名ID','训练营','批次','最后提交时间UTC','下一任务','当前状态'])
    for item in data['followup']:
        e=enrollments[item['enrollment_id']]
        writer.writerow([safe(v) for v in [e.user_id,item['nickname'],e.id,camps[e.bootcamp_id],batches.get(e.batch_id,'未分批'),item['last_submitted_at'],item['next_day'],'需修改' if subs.get((e.id,item['next_day']))=='rejected' else '可学习']])
    record(db,admin.id,'生成当前待跟进名单','export',detail={'count':len(ids)},event_type='export.followup.generated',camp_id=int(camp) if camp else None,batch_id=int(batch) if batch else None)
    db.commit()
    return StreamingResponse(iter([output.getvalue().encode('utf-8-sig')]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=current-followup.csv'})
