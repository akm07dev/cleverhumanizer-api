import asyncio
import logging

from curl_cffi import requests as curl_requests

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
        
        try:
            result_text = await self.session_manager.do_rewrite(
                text=request.text,
                style=request.style,
                type_generation=request.type_generation
            )
            return RewriteResponse(text=result_text)
        except Exception as exc:
            raise ProviderError(f"Upstream Playwright request failed: {exc}") from exc
