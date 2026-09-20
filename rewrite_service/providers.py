from __future__ import annotations

import logging

import httpx

from .config import Settings
from .models import RewriteRequest, RewriteResponse
from .session import SessionManager

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    pass


class CleverHumanizerProvider:
    """Proxy rewrites through CleverHumanizer.ai using a Playwright-bootstrapped
    browser session for authentication.

    On auth failure (HTTP 419 / 429), the session is invalidated and the
    request is retried once with a fresh session.
    """

    UPSTREAM_URL = "https://cleverhumanizer.ai/rewrite"

    def __init__(self, settings: Settings) -> None:
        self.session_manager = SessionManager(
            ttl_seconds=settings.session_ttl_seconds,
        )

    async def rewrite(self, request: RewriteRequest) -> RewriteResponse:
        return await self._try_rewrite(request, allow_retry=True)

    async def _try_rewrite(
        self, request: RewriteRequest, *, allow_retry: bool
    ) -> RewriteResponse:
        session = await self.session_manager.get_session()

        headers = {
            "X-CSRF-TOKEN": session.csrf_token,
            "X-Guest-Access-Token": session.guest_access_token,
            "X-Client-Fingerprint": session.client_fingerprint,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Referer": "https://cleverhumanizer.ai/",
            "Origin": "https://cleverhumanizer.ai",
        }

        payload = {
            "text": request.text,
            "style": request.style,
            "type_generation": request.type_generation,
        }
        if request.html:
            payload["html"] = request.html

        cookie_header = "; ".join(
            f"{k}={v}" for k, v in session.cookies.items()
        )

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    self.UPSTREAM_URL,
                    json=payload,
                    headers={**headers, "Cookie": cookie_header},
                )

                # Auth / rate-limit failure → retry with a fresh session once
                if response.status_code in (419, 429) and allow_retry:
                    logger.warning(
                        "Upstream returned %s — invalidating session and retrying",
                        response.status_code,
                    )
                    await self.session_manager.invalidate()
                    return await self._try_rewrite(request, allow_retry=False)

                response.raise_for_status()
                body = response.json()
                
                # The upstream returns a job_id which we need to poll
                job_id = body.get("job_id")
                if not job_id:
                    raise ProviderError(f"No job_id in upstream response: {body!r}")
                
                import asyncio
                
                # Poll for completion
                poll_url = f"https://cleverhumanizer.ai/humanize-jobs/{job_id}"
                while True:
                    await asyncio.sleep(1.0)
                    poll_response = await client.get(
                        poll_url,
                        headers={**headers, "Cookie": cookie_header},
                    )
                    poll_response.raise_for_status()
                    poll_body = poll_response.json()
                    
                    status = poll_body.get("status")
                    if status == "completed":
                        result_text = poll_body.get("data", {}).get("text", "")
                        return RewriteResponse(text=result_text)
                    elif status == "processing":
                        continue
                    else:
                        raise ProviderError(f"Job failed or unexpected status: {poll_body!r}")

        except httpx.HTTPError as exc:
            error_body = ""
            if isinstance(exc, httpx.HTTPStatusError):
                error_body = f" Body: {exc.response.text}"
            raise ProviderError(
                f"Upstream request failed: {exc}.{error_body}"
            ) from exc
