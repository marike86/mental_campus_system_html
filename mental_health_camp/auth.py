import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status, Response, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from passlib.context import CryptContext
from database import get_db
from models.user import User
from config import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_ACCESS_TOKEN_EXPIRE_MINUTES
from utils.csrf import validate_csrf_token

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

REDIRECT_RESPONSE = status.HTTP_303_SEE_OTHER


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    if "sub" in to_encode and not isinstance(to_encode["sub"], str):
        to_encode["sub"] = str(to_encode["sub"])
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def _extract_user_id(payload: dict) -> Optional[int]:
    sub = payload.get("sub")
    if sub is None:
        return None
    try:
        return int(sub)
    except (TypeError, ValueError):
        logger.warning("JWT payload 'sub' 无法转换为整数: %s", sub)
        return None


async def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=REDIRECT_RESPONSE, headers={"Location": "/login"})
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        logger.warning("JWT 令牌验证失败: %s", e)
        raise HTTPException(status_code=REDIRECT_RESPONSE, headers={"Location": "/login"})
    user_id = _extract_user_id(payload)
    if user_id is None:
        raise HTTPException(status_code=REDIRECT_RESPONSE, headers={"Location": "/login"})
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        logger.warning("JWT 中的用户 ID %d 不存在", user_id)
        raise HTTPException(status_code=REDIRECT_RESPONSE, headers={"Location": "/login"})
    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return current_user


async def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要超级管理员权限")
    return current_user


async def require_reviewer(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("admin", "super_admin", "reviewer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要审核权限")
    if current_user.role == "reviewer" and not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="审核员账户已被禁用")
    return current_user


async def get_optional_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    user_id = _extract_user_id(payload)
    if user_id is None:
        return None
    return db.query(User).filter(User.id == user_id).first()


async def verify_csrf(request: Request, csrf_token: str = Form("")) -> None:
    """CSRF验证依赖，用于POST路由

    在路由函数参数中添加 csrf_token: str = Form(...) 和此依赖即可启用CSRF防护。
    """
    import secrets as _secrets
    cookie_token = request.cookies.get("csrf_token", "")
    if not cookie_token:
        logger.warning("CSRF验证失败：cookie中无token [path=%s]", request.url.path)
        raise HTTPException(status_code=403, detail="CSRF token缺失")
    if not _secrets.compare_digest(cookie_token, csrf_token):
        logger.warning("CSRF验证失败：token不匹配 [path=%s]", request.url.path)
        raise HTTPException(status_code=403, detail="CSRF token无效")
