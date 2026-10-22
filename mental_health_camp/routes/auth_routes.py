from datetime import date, timedelta, datetime, timezone
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from auth import verify_password, get_password_hash, create_access_token, get_current_user, get_optional_user, verify_csrf
from config import APP_NAME, DEBUG
from utils.sanitize import sanitize_text, sanitize_email, validate_password_strength
from templates_config import templates

router = APIRouter(tags=["auth"])


@router.get("/login")
async def login_page(request: Request, current_user: User = Depends(get_optional_user), registered: str = None):
    if current_user:
        if current_user.role in ("admin", "super_admin"):
            return RedirectResponse("/admin/bootcamps", status_code=302)
        if current_user.role == "reviewer":
            return RedirectResponse("/review/pending?view=mine", status_code=302)
        return RedirectResponse("/user/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "app_name": APP_NAME, "registered": registered})


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "app_name": APP_NAME,
            "error": "邮箱或密码错误",
        })
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    token = create_access_token({"sub": user.id})
    if user.role in ("admin", "super_admin"):
        response = RedirectResponse("/admin/bootcamps", status_code=302)
    elif user.role == "reviewer":
        response = RedirectResponse("/review/pending?view=mine", status_code=302)
    else:
        response = RedirectResponse("/user/dashboard", status_code=302)
    response.set_cookie(
        "access_token", token,
        httponly=True,
        secure=not DEBUG,
        samesite="lax"
    )
    return response


@router.get("/register")
async def register_page(request: Request, current_user: User = Depends(get_optional_user)):
    if current_user:
        return RedirectResponse("/user/dashboard", status_code=302)
    return templates.TemplateResponse("register.html", {"request": request, "app_name": APP_NAME})


@router.post("/register")
async def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    nickname: str = Form(...),
    college: str = Form(""),
    student_id: str = Form(""),
    grade: str = Form(""),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    # 输入清理
    email = sanitize_email(email)
    if not email:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "app_name": APP_NAME,
            "error": "邮箱格式不正确",
        })
    nickname = sanitize_text(nickname)
    college = sanitize_text(college)
    student_id = sanitize_text(student_id)
    grade = sanitize_text(grade)
    # 密码强度验证
    pwd_valid, pwd_error = validate_password_strength(password)
    if not pwd_valid:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "app_name": APP_NAME,
            "error": pwd_error,
        })
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "app_name": APP_NAME,
            "error": "该邮箱已被注册",
        })
    user = User(
        email=email,
        nickname=nickname,
        hashed_password=get_password_hash(password),
        role="user",
        college=college.strip() if college else None,
        student_id=student_id.strip() if student_id else None,
        grade=grade.strip() if grade else None,
    )
    db.add(user)
    db.commit()
    return RedirectResponse("/login?registered=1", status_code=302)


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("access_token")
    return response
