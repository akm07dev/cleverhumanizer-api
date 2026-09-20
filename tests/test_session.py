"""Unit tests for the session bootstrap module.

All Playwright interaction is mocked — these tests verify:
- SessionManager caching / TTL logic
- CleverSession dataclass
- Guest access token generation
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from rewrite_service.session import (
    CleverSession,
    SessionManager,
    _generate_guest_access_token,
)


def _make_session(**overrides: object) -> CleverSession:
    defaults: dict[str, object] = {
        "cookies": {"XSRF-TOKEN": "abc", "clever_ai_humanizer_session": "xyz"},
        "csrf_token": "tok_csrf_1234567890",
        "guest_access_token": "gat_abcdefg1234567890abcdefg1234567890a",
        "client_fingerprint": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
    }
    defaults.update(overrides)
    return CleverSession(**defaults)  # type: ignore[arg-type]


# ── Guest access token generation ─────────────────────────────────────


def test_guest_access_token_length() -> None:
    token = _generate_guest_access_token()
    assert len(token) == 43, f"Expected 43 chars, got {len(token)}: {token}"


def test_guest_access_token_is_base64url() -> None:
    token = _generate_guest_access_token()
    assert "+" not in token
    assert "/" not in token
    assert "=" not in token


def test_guest_access_tokens_are_unique() -> None:
    tokens = {_generate_guest_access_token() for _ in range(50)}
    assert len(tokens) == 50


# ── SessionManager caching ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_manager_caches() -> None:
    """get_session should return the same object when not expired."""
    mock_bootstrap = AsyncMock(return_value=_make_session())

    with patch("rewrite_service.session.bootstrap_session", mock_bootstrap):
        mgr = SessionManager(ttl_seconds=300)
        s1 = await mgr.get_session()
        s2 = await mgr.get_session()

    assert s1 is s2
    mock_bootstrap.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_manager_rebootstraps_after_ttl() -> None:
    """After TTL expires, a fresh session should be bootstrapped."""
    first = _make_session(created_at=time.monotonic() - 9999)
    second = _make_session()

    mock_bootstrap = AsyncMock(side_effect=[first, second])

    with patch("rewrite_service.session.bootstrap_session", mock_bootstrap):
        mgr = SessionManager(ttl_seconds=1)
        s1 = await mgr.get_session()
        # First call returned the expired session — next call should re-bootstrap
        s2 = await mgr.get_session()

    assert s1 is first
    assert s2 is second
    assert mock_bootstrap.await_count == 2


@pytest.mark.asyncio
async def test_session_manager_invalidate() -> None:
    """invalidate() forces a fresh bootstrap on the next get_session."""
    mock_bootstrap = AsyncMock(
        side_effect=[_make_session(), _make_session()]
    )

    with patch("rewrite_service.session.bootstrap_session", mock_bootstrap):
        mgr = SessionManager(ttl_seconds=300)
        s1 = await mgr.get_session()
        await mgr.invalidate()
        s2 = await mgr.get_session()

    assert s1 is not s2
    assert mock_bootstrap.await_count == 2
