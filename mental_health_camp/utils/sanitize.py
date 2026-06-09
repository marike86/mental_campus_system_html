import re
import html
import logging

logger = logging.getLogger(__name__)

# 最小密码长度
MIN_PASSWORD_LENGTH = 8


def sanitize_text(value: str) -> str:
    """清理文本输入，防止XSS攻击

    - 去除HTML标签
    - 转义特殊字符
    - 去除首尾空白
    """
    if not value:
        return ""
    # 先转义HTML特殊字符
    value = html.escape(value.strip(), quote=True)
    # 去除可能的HTML标签残留
    value = re.sub(r'<[^>]*>', '', value)
    return value.strip()


def sanitize_email(value: str) -> str:
    """验证并清理邮箱地址

    - 去除首尾空白
    - 验证邮箱格式
    - 转为小写
    """
    if not value:
        return ""
    value = value.strip().lower()
    # 基本邮箱格式验证
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, value):
        return ""
    return value


def validate_password_strength(password: str) -> tuple:
    """验证密码强度

    返回 (is_valid: bool, error_message: str)
    要求：至少8位，包含字母和数字
    """
    if not password:
        return False, "密码不能为空"
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"密码长度不能少于{MIN_PASSWORD_LENGTH}位"
    if not re.search(r'[a-zA-Z]', password):
        return False, "密码必须包含字母"
    if not re.search(r'[0-9]', password):
        return False, "密码必须包含数字"
    return True, ""
