import copy
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from auth import require_admin, verify_csrf
from database import get_db
from models.day_form import DayForm
from models.workflow import DayFormVersion
from services.versions import publish, write_lock
from templates_config import templates

router = APIRouter(tags=["versions"])


def find_form(db, camp, day):
    form = db.query(DayForm).filter_by(bootcamp_id=camp, day_number=day).first()
    if not form:
        raise HTTPException(404, "表单不存在")
    return form


@router.get("/admin/bootcamp/{camp}/day/{day}/versions")
async def versions(request: Request, camp: int, day: int, admin=Depends(require_admin), db: Session=Depends(get_db)):
    form = find_form(db, camp, day)
    versions = db.query(DayFormVersion).filter_by(day_form_id=form.id).order_by(DayFormVersion.version.desc()).all()
    return templates.TemplateResponse("admin/versions.html", dict(request=request, user=admin, form=form, versions=versions))


@router.get("/admin/bootcamp/{camp}/day/{day}/preview")
async def preview(request: Request, camp: int, day: int, admin=Depends(require_admin), db: Session=Depends(get_db)):
    return templates.TemplateResponse("admin/preview.html", dict(request=request, user=admin, form=find_form(db, camp, day)))


@router.post("/admin/bootcamp/{camp}/day/{day}/publish")
async def publish_form(camp: int, day: int, admin=Depends(require_admin), db: Session=Depends(get_db), csrf=Depends(verify_csrf)):
    publish(db, find_form(db, camp, day), admin.id)
    db.commit()
    return RedirectResponse(f"/admin/bootcamp/{camp}/day/{day}/versions", 303)


@router.post("/admin/bootcamp/{camp}/day/{day}/restore/{version_id}")
async def restore(camp: int, day: int, version_id: int, admin=Depends(require_admin), db: Session=Depends(get_db), csrf=Depends(verify_csrf)):
    write_lock(db)
    form = find_form(db, camp, day)
    version = db.get(DayFormVersion, version_id)
    if not version or version.day_form_id != form.id:
        raise HTTPException(404, "版本不存在")
    form.questions = copy.deepcopy(version.questions)
    db.commit()
    return RedirectResponse(f"/admin/bootcamp/{camp}/day/{day}", 303)
