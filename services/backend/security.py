"""认证与会话安全工具。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from argon2 import PasswordHasher


_PASSWORD_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    """哈希用户密码。"""
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """校验用户密码。"""
    try:
        return bool(_PASSWORD_HASHER.verify(password_hash, password))
    except Exception:
        return False


def new_session_token() -> str:
    """生成新的会话令牌。"""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """对会话令牌做稳定哈希，避免明文落库。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def utcnow() -> datetime:
    """返回 UTC 当前时间。"""
    return datetime.now(timezone.utc)


def expire_after(hours: int) -> datetime:
    """计算会话过期时间。"""
    return utcnow() + timedelta(hours=max(1, int(hours)))


def build_session_cookie(token: str, *, max_age_hours: int) -> Dict[str, Any]:
    """构造统一 Cookie 参数。"""
    return {
        "key": token,
        "httponly": True,
        "samesite": "lax",
        "secure": False,
        "max_age": max(1, int(max_age_hours)) * 3600,
        "path": "/",
    }
