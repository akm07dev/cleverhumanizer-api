"""Browser-based session bootstrap for CleverHumanizer.ai.

Uses Playwright to load the real frontend in headless Chromium, intercept
the ``/fingerprint-init`` request, and capture the three auth headers plus
session cookies.  A ``SessionManager`` caches the result with a configurable
TTL so we don't launch a browser on every rewrite.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass, field

from playwright.async_api import async_playwright, Request

logger = logging.getLogger(__name__)

BASE_URL = "https://cleverhumanizer.ai"


@dataclass
class CleverSession:
    """All credentials needed to call the upstream rewrite API."""

    cookies: dict[str, str]
    csrf_token: str
    guest_access_token: str
    client_fingerprint: str
    created_at: float = field(default_factory=time.monotonic)


async def bootstrap_session() -> CleverSession:
    """Launch headless Chromium, load the CleverHumanizer homepage, and
    capture the auth metadata from the ``/fingerprint-init`` request that
    the frontend fires during initialization.

    Returns a fully populated :class:`CleverSession`.
    """
    logger.info("Bootstrapping new CleverHumanizer session via Playwright …")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Wait for the frontend to fire POST /fingerprint-init — it carries
        # all three custom headers we need.
        async with page.expect_request(
            lambda r: "/fingerprint-init" in r.url and r.method == "POST",
            timeout=30_000,
        ) as request_info:
            await page.goto(BASE_URL, wait_until="domcontentloaded")

        request: Request = await request_info.value

        headers = request.headers
        csrf_token = headers.get("x-csrf-token", "")
        guest_access_token = headers.get("x-guest-access-token", "")
        client_fingerprint = headers.get("x-client-fingerprint", "")

        if not csrf_token or not client_fingerprint:
            await browser.close()
            raise RuntimeError(
                "Failed to capture auth headers from /fingerprint-init. "
                f"Got csrf={csrf_token!r}, fingerprint={client_fingerprint!r}"
            )

        # If the guest access token wasn't in the intercepted headers,
        # generate one ourselves (same algorithm as csrf.min.js).
        if not guest_access_token:
            guest_access_token = _generate_guest_access_token()

        raw_cookies = await context.cookies(BASE_URL)
        cookies = {c["name"]: c["value"] for c in raw_cookies}

        await browser.close()

    session = CleverSession(
        cookies=cookies,
        csrf_token=csrf_token,
        guest_access_token=guest_access_token,
        client_fingerprint=client_fingerprint,
    )
    logger.info(
        "Session bootstrapped: fingerprint=%s, cookies=%s",
        client_fingerprint[:8] + "…",
        list(cookies.keys()),
    )
    return session


def _generate_guest_access_token() -> str:
    """Replicate the frontend's guest-token generation:

    32 random bytes → base64 → base64url → strip padding.
    Produces a 43-character string.
    """
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()


class SessionManager:
    """Thread-safe cache for a :class:`CleverSession` with TTL-based expiry."""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self._ttl = ttl_seconds
        self._session: CleverSession | None = None
        self._lock = asyncio.Lock()

    async def get_session(self) -> CleverSession:
        """Return a cached session, bootstrapping a new one if needed."""
        async with self._lock:
            if self._session is None or self._is_expired(self._session):
                self._session = await bootstrap_session()
            return self._session

    async def invalidate(self) -> None:
        """Force the next call to ``get_session`` to re-bootstrap."""
        async with self._lock:
            self._session = None

    def _is_expired(self, session: CleverSession) -> bool:
        return (time.monotonic() - session.created_at) >= self._ttl
