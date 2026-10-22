import secrets
import logging
from fastapi import Request, HTTPException

logger = logging.getLogger(__name__)

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"
CSRF_TOKEN_LENGTH = 64


def generate_csrf_token() -> str:
    """生成一个随机的CSRF token"""
    return secrets.token_hex(CSRF_TOKEN_LENGTH // 2)


def get_csrf_token_from_cookie(request: Request) -> str:
    """从请求cookie中获取CSRF token"""
    return request.cookies.get(CSRF_COOKIE_NAME, "")


def get_or_create_csrf_token(request: Request) -> str:
    """获取现有CSRF token或生成新的"""
    token = get_csrf_token_from_cookie(request)
    if not token:
        token = getattr(request.state, "csrf_token", None)
        if not token:
            token = generate_csrf_token()
            request.state.csrf_token = token
    return token


def validate_csrf_token(request: Request) -> None:
    """验证CSRF token，失败时抛出403异常

    验证逻辑：
    1. 从cookie中获取服务端设置的token
    2. 从表单数据或header中获取客户端提交的token
    3. 使用secrets.compare_digest进行时间安全的比较
    """
    cookie_token = get_csrf_token_from_cookie(request)
    if not cookie_token:
        logger.warning("CSRF验证失败：cookie中无token [path=%s]", request.url.path)
        raise HTTPException(status_code=403, detail="CSRF token缺失")

    # 优先从表单数据获取，其次从header获取
    form_token = ""
    if hasattr(request, "_form_data") and request._form_data:
        form_token = request._form_data.get("csrf_token", "")
    if not form_token:
        form_token = request.headers.get(CSRF_HEADER_NAME, "")

    if not form_token:
        logger.warning("CSRF验证失败：请求中无token [path=%s]", request.url.path)
        raise HTTPException(status_code=403, detail="CSRF token缺失")

    if not secrets.compare_digest(cookie_token, form_token):
        logger.warning("CSRF验证失败：token不匹配 [path=%s]", request.url.path)
        raise HTTPException(status_code=403, detail="CSRF token无效")
