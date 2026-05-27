import os
import json
import base64
import logging
from config import ENCRYPTION_KEY, ENCRYPTION_ENABLED

logger = logging.getLogger(__name__)

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    if not ENCRYPTION_ENABLED:
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.warning("cryptography库未安装，加密功能不可用")
        return None
    key = ENCRYPTION_KEY
    if not key:
        key_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".encryption_key")
        if os.path.exists(key_file):
            with open(key_file, "r") as f:
                key = f.read().strip()
        else:
            key = Fernet.generate_key().decode()
            with open(key_file, "w") as f:
                f.write(key)
            logger.info(f"已生成新的加密密钥并保存到 {key_file}")
    if isinstance(key, str):
        key = key.encode()
    _fernet = Fernet(key)
    return _fernet


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
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
