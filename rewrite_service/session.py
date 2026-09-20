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
    user_agent: str
    created_at: float = field(default_factory=time.monotonic)


async def bootstrap_session() -> CleverSession:
    """Launch headless Chromium, load the CleverHumanizer homepage, and
    capture the auth metadata from the ``/fingerprint-init`` request that
    the frontend fires during initialization.

    Returns a fully populated :class:`CleverSession`.
    """
    logger.info("Bootstrapping new CleverHumanizer session via Playwright …")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # Wait for the frontend to load
        await page.goto(BASE_URL, wait_until="domcontentloaded")

        # Fill the quill editor with dummy text and submit to trigger Turnstile
        logger.info("Typing dummy text to trigger Turnstile...")
        await page.locator('.ql-editor').first.click()
        await page.keyboard.type("This is a dummy text string designed specifically to be long enough to bypass the thirty word minimum limit imposed by the upstream API. By sending this text, we ensure that the warm-up call succeeds and properly initializes the browser session without throwing any HTTP 422 validation errors along the way.")
        
        # Intercept the successful fingerprint and rewrite requests to get tokens
        csrf_token = ""
        guest_access_token = ""
        client_fingerprint = ""
        user_agent = ""

        async def handle_request(route, request):
            nonlocal csrf_token, guest_access_token, client_fingerprint, user_agent
            if "/fingerprint-init" in request.url or "/rewrite" in request.url:
                csrf_token = request.headers.get("x-csrf-token", csrf_token)
                guest_access_token = request.headers.get("x-guest-access-token", guest_access_token)
                client_fingerprint = request.headers.get("x-client-fingerprint", client_fingerprint)
                user_agent = request.headers.get("user-agent", user_agent)
            await route.continue_()

        await page.route("**/*", handle_request)
        
        # Click the submit button
        logger.info("Clicking submit button...")
        await page.locator('.submitQuill').first.click()
        
        # Wait for the job completion which means Turnstile was solved
        try:
            logger.info("Waiting for successful humanize-jobs response...")
            async with page.expect_response(lambda r: "/humanize-jobs" in r.url and r.status == 200, timeout=20_000):
                pass
            logger.info("Turnstile solved successfully!")
        except Exception as e:
            logger.warning(f"Timeout waiting for dummy rewrite to complete: {e}")

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
        user_agent=user_agent,
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
    """Uses Playwright to perform the rewrite directly in the browser."""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self._lock = asyncio.Lock()

    async def get_session(self):
        # Kept for compatibility but not used
        pass

    async def invalidate(self) -> None:
        pass

    async def do_rewrite(self, text: str, style: str, type_generation: str) -> str:
        async with self._lock:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False)
                context = await browser.new_context()
                page = await context.new_page()

                try:
                    await page.goto(BASE_URL, wait_until="domcontentloaded")
                    
                    logger.info("Typing text for rewrite with human delay...")
                    await page.locator('.ql-editor').first.click()
                    await page.keyboard.type(text, delay=20)
                    
                    # Set up an event listener to capture the successful humanize-jobs response
                    response_data = None
                    async def handle_response(response):
                        nonlocal response_data
                        if "/humanize-jobs" in response.url and response.status == 200:
                            try:
                                body = await response.json()
                                if body.get("status") == "completed":
                                    response_data = body
                            except Exception:
                                pass

                    page.on("response", handle_response)

                    # Click the submit button initially
                    logger.info("Clicking submit button...")
                    await asyncio.sleep(1)
                    await page.locator('.submitQuill').first.click()
                    
                    # Robust loop to handle modals, turnstile, and wait for completion
                    for i in range(40): # 80 seconds timeout (2s per loop)
                        if response_data is not None:
                            break
                            
                        await asyncio.sleep(2)
                        
                        # 1. Check for "Oops" modal and dismiss it without resubmitting!
                        try:
                            oops_modal = page.locator('#limitModal')
                            if await oops_modal.count() > 0 and await oops_modal.is_visible():
                                logger.info("Oops modal detected! Attempting to dismiss via JS...")
                                await page.evaluate('''() => {
                                    const btn = document.querySelector('#limitModal button[data-bs-dismiss="modal"]');
                                    if(btn) btn.click();
                                    
                                    // Also remove the modal backdrop just in case it gets stuck
                                    const backdrops = document.querySelectorAll('.modal-backdrop');
                                    backdrops.forEach(b => b.remove());
                                    document.body.classList.remove('modal-open');
                                }''')
                                await asyncio.sleep(1)
                        except Exception as e:
                            pass
                            
                        # 2. Check for Turnstile and click it if not yet solved
                        try:
                            turnstile_token = await page.locator('[name="cf-turnstile-response"]').input_value(timeout=500)
                        except Exception:
                            turnstile_token = ""
                            
                        if not turnstile_token:
                            target_frame = None
                            for f in page.frames:
                                if "challenges.cloudflare.com" in f.url:
                                    target_frame = f
                                    break
                            
                            if target_frame:
                                logger.info("Turnstile frame detected! Clicking body...")
                                await target_frame.locator('body').click(force=True, delay=150)
                        else:
                            # If token is present but we haven't got the response, maybe we need to click submit again!
                            if i % 3 == 0:  # Only click every 6 seconds to avoid spamming
                                logger.info("Turnstile solved (token present). Re-clicking submit just in case it didn't auto-submit...")
                                await page.locator('.submitQuill').first.click(force=True)
                            
                    if not response_data:
                        raise RuntimeError("Timeout waiting for successful humanize-jobs response.")
                        
                    result_text = response_data.get("data", {}).get("text", "")
                    logger.info("Rewrite completed successfully in browser!")
                    return result_text
                finally:
                    await browser.close()
