from datetime import date, timedelta, datetime, timezone
from urllib.parse import urlparse
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from auth import verify_password, get_password_hash, create_access_token, get_current_user, get_optional_user, verify_csrf
from config import APP_NAME, DEBUG, LOGIN_RATE_LIMIT, LOGIN_RATE_WINDOW, REGISTER_RATE_LIMIT, REGISTER_RATE_WINDOW
from utils.ratelimit import hit
from utils.sanitize import (sanitize_text, sanitize_email, validate_password_strength,
                             check_length, MAX_NICKNAME_LENGTH, MAX_FIELD_LENGTH)
from templates_config import templates

router = APIRouter(tags=["auth"])

# 用于在邮箱不存在时也执行一次密码校验，避免通过响应耗时区分账号是否存在。
_DUMMY_HASH = "$2b$12$QLWuR7FJ/h6ibUY65FDz8exxcY1NPu.A9CxpvpCR3wxuLHogXVBM2"


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _is_cross_site(request: Request) -> bool:
    """判断请求是否来自其他站点（用于保护 GET 形式的登出）。"""
    site = request.headers.get("sec-fetch-site", "").lower()
    if site:
        return site == "cross-site"
    referer = request.headers.get("referer")
    if referer:
        try:
            return urlparse(referer).netloc != request.headers.get("host", "")
        except ValueError:
            return True
    return False


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
    email = (email or "").strip().lower()
    ip = _client_ip(request)
    if not DEBUG:
        # 生产环境对登录、注册做限流，拦截暴力破解与批量注册。
        allowed, retry_after = hit(f"login:{ip}:{email}", LOGIN_RATE_LIMIT, LOGIN_RATE_WINDOW)
        if not allowed:
            raise HTTPException(status_code=429, detail="登录尝试过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
        allowed, retry_after = hit(f"login-ip:{ip}", LOGIN_RATE_LIMIT * 3, LOGIN_RATE_WINDOW)
        if not allowed:
            raise HTTPException(status_code=429, detail="登录尝试过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
    user = db.query(User).filter(User.email == email).first()
    if not user:
        # 邮箱不存在时同样执行一次密码校验，抹平时间差。
        verify_password(password, _DUMMY_HASH)
        return templates.TemplateResponse("login.html", {
            "request": request,
            "app_name": APP_NAME,
            "error": "邮箱或密码错误",
        })
    if not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "app_name": APP_NAME,
            "error": "邮箱或密码错误",
        })
    if user.is_active is False:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "app_name": APP_NAME,
            "error": "账号已被禁用，请联系管理员",
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
    if not DEBUG:
        allowed, retry_after = hit(f"register:{_client_ip(request)}", REGISTER_RATE_LIMIT, REGISTER_RATE_WINDOW)
        if not allowed:
            raise HTTPException(status_code=429, detail="注册请求过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
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
    for value, limit, label in ((nickname, MAX_NICKNAME_LENGTH, "昵称"),
                                (college, MAX_FIELD_LENGTH, "学院"),
                                (student_id, MAX_FIELD_LENGTH, "学号"),
                                (grade, MAX_FIELD_LENGTH, "年级")):
        ok, message = check_length(value, limit, label)
        if not ok:
            return templates.TemplateResponse("register.html", {
                "request": request,
                "app_name": APP_NAME,
                "error": message,
            })
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


@router.post("/logout")
async def logout(request: Request, _csrf: None = Depends(verify_csrf)):
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("access_token")
    return response


@router.get("/logout")
async def logout_get(request: Request):
    """兼容旧书签的登出入口：仅接受同站导航，跨站请求一律拒绝。"""
    if _is_cross_site(request):
        raise HTTPException(status_code=403, detail="请从站内退出登录")
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("access_token")
    return response
