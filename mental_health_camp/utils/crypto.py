import os
import json
import logging
from config import ENCRYPTION_KEY, ENCRYPTION_ENABLED

logger = logging.getLogger(__name__)

_fernet = None
_secret_fernet = None
_KEY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".encryption_key")


def _load_key() -> bytes:
    """读取加密密钥：优先环境变量，其次密钥文件，最后自动生成并保存。"""
    key = ENCRYPTION_KEY
    if not key:
        if os.path.exists(_KEY_FILE):
            with open(_KEY_FILE, "r") as f:
                key = f.read().strip()
        else:
            from cryptography.fernet import Fernet
            key = Fernet.generate_key().decode()
            with open(_KEY_FILE, "w") as f:
                f.write(key)
            logger.info("已生成新的加密密钥并保存到 %s（该文件不可提交到仓库）", _KEY_FILE)
    return key.encode("utf-8") if isinstance(key, str) else key


def _build_fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.warning("cryptography库未安装，加密功能不可用")
        return None
    try:
        return Fernet(_load_key())
    except Exception as exc:  # 密钥格式非法时退回未加密状态
        logger.error("加密密钥不可用: %s", exc)
        return None


def _get_fernet():
    """答案数据加密：受 ENCRYPTION_ENABLED 控制。"""
    global _fernet
    if not ENCRYPTION_ENABLED:
        return None
    if _fernet is None:
        _fernet = _build_fernet()
    return _fernet


def _get_secret_fernet():
    """凭据加密：始终启用，不受 ENCRYPTION_ENABLED 影响。"""
    global _secret_fernet
    if _secret_fernet is None:
        _secret_fernet = _build_fernet()
    return _secret_fernet


def encrypt_data(data: dict) -> str:
    f = _get_fernet()
    if f is None:
        return json.dumps(data, ensure_ascii=False)
    json_str = json.dumps(data, ensure_ascii=False).encode("utf-8")
    encrypted = f.encrypt(json_str)
    return encrypted.decode("utf-8")


def decrypt_data(raw: str) -> dict:
    f = _get_fernet()
    if f is None:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    try:
        decrypted = f.decrypt(raw.encode("utf-8"))
        return json.loads(decrypted.decode("utf-8"))
    except Exception:
        # 兼容加密前写入的历史明文数据。
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}


def encrypt_secret(value: str) -> str:
    """加密凭据（如大模型 API Key），始终使用对称加密保存。"""
    if not value:
        return ""
    f = _get_secret_fernet()
    if f is None:
        raise RuntimeError("缺少 cryptography 库，无法安全保存凭据")
    return f.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(raw: str) -> str:
    """解密凭据；密钥不匹配时返回空串，不抛出异常以免泄露信息。"""
    if not raw:
        return ""
    f = _get_secret_fernet()
    if f is None:
        return raw
    try:
        return f.decrypt(raw.encode("utf-8")).decode("utf-8")
    except Exception:
        logger.warning("凭据解密失败：密钥不匹配或数据已损坏")
        return ""
