import base64
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from Corv.config import settings


def _get_fernet(key: Optional[str] = None) -> Fernet:
    key = key or settings.module_secret_key
    if not key:
        raise RuntimeError("MODULE_SECRET_KEY must be set for module secrets")
    try:
        decoded = base64.urlsafe_b64decode(key)
    except Exception:
        raise RuntimeError("MODULE_SECRET_KEY must be a urlsafe base64-encoded key")
    if len(decoded) != 32:
        raise RuntimeError("MODULE_SECRET_KEY must decode to 32 bytes")
    return Fernet(key)


def encrypt_value(value: str, key: Optional[str] = None) -> str:
    f = _get_fernet(key)
    return f.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(value: str, key: Optional[str] = None) -> str:
    f = _get_fernet(key)
    try:
        return f.decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Invalid secret token or key") from exc
