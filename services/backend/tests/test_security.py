"""产品后端安全工具测试。"""

from __future__ import annotations

from backend.security import (
    build_session_cookie,
    hash_password,
    hash_session_token,
    new_session_token,
    verify_password,
)


def test_password_hash_and_verify() -> None:
    """密码哈希后应能正确校验。"""
    password_hash = hash_password("fusion-secret")
    assert verify_password("fusion-secret", password_hash) is True
    assert verify_password("wrong-password", password_hash) is False


def test_session_token_helpers() -> None:
    """会话令牌应生成稳定哈希与合理 Cookie。"""
    token = new_session_token()
    assert token
    assert hash_session_token(token) == hash_session_token(token)
    cookie = build_session_cookie(token, max_age_hours=24)
    assert cookie["key"] == token
    assert cookie["max_age"] == 24 * 3600
