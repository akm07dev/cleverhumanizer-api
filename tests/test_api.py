from unittest.mock import AsyncMock, MagicMock, patch

from rewrite_service.models import RewriteRequest
from rewrite_service.providers import CleverHumanizerProvider
from rewrite_service.session import CleverSession


def _make_fake_response(status_code: int, body: dict | None = None) -> MagicMock:
    """Create a mock httpx.Response with synchronous .json() and .raise_for_status()."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {}
    resp.raise_for_status = MagicMock()
    return resp


def _make_fake_client(post_responses: list[MagicMock], get_responses: list[MagicMock] | None = None) -> AsyncMock:
    """Create a mock httpx.AsyncClient that returns the given responses."""
    client = AsyncMock()
    if len(post_responses) == 1:
        client.post.return_value = post_responses[0]
    else:
        client.post.side_effect = post_responses
        
    if get_responses:
        if len(get_responses) == 1:
            client.get.return_value = get_responses[0]
        else:
            client.get.side_effect = get_responses

    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _make_session(**overrides: object) -> CleverSession:
    defaults: dict[str, object] = {
        "cookies": {"XSRF-TOKEN": "xsrf", "clever_ai_humanizer_session": "sess"},
        "csrf_token": "tok_csrf_test",
        "guest_access_token": "gat_test_token",
        "client_fingerprint": "aabbccdd11223344",
    }
    defaults.update(overrides)
    return CleverSession(**defaults)  # type: ignore[arg-type]


def test_health() -> None:
    from rewrite_service.app import app
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_rewrite_returns_upstream_result() -> None:
    """POST /v1/rewrite should call the upstream, poll the job, and return the result."""
    fake_post_response = _make_fake_response(200, {
        "job_id": "job123",
        "status": "processing"
    })
    
    fake_get_response_1 = _make_fake_response(200, {
        "job_id": "job123",
        "status": "processing"
    })
    
    fake_get_response_2 = _make_fake_response(200, {
        "job_id": "job123",
        "status": "completed",
        "data": {"text": "rewritten text"}
    })
    
    fake_client = _make_fake_client([fake_post_response], [fake_get_response_1, fake_get_response_2])

    from rewrite_service.config import load_settings
    settings = load_settings()

    provider = CleverHumanizerProvider(settings)
    provider.session_manager.get_session = AsyncMock(return_value=_make_session())

    with patch("rewrite_service.providers.httpx.AsyncClient", return_value=fake_client):
        with patch("asyncio.sleep", new_callable=AsyncMock): # don't actually sleep
            result = await provider.rewrite(RewriteRequest(text="Hello world"))

    assert result.text == "rewritten text"


async def test_sends_correct_headers() -> None:
    """All three auth headers must be forwarded to the upstream."""
    fake_post_response = _make_fake_response(200, {"job_id": "job123"})
    fake_get_response = _make_fake_response(200, {"status": "completed", "data": {"text": "ok"}})
    fake_client = _make_fake_client([fake_post_response], [fake_get_response])

    from rewrite_service.config import load_settings
    settings = load_settings()

    provider = CleverHumanizerProvider(settings)
    provider.session_manager.get_session = AsyncMock(return_value=_make_session())

    with patch("rewrite_service.providers.httpx.AsyncClient", return_value=fake_client):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await provider.rewrite(RewriteRequest(text="test"))

    call_kwargs = fake_client.post.call_args
    sent_headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
    assert sent_headers["X-CSRF-TOKEN"] == "tok_csrf_test"
    assert sent_headers["X-Guest-Access-Token"] == "gat_test_token"
    assert sent_headers["X-Client-Fingerprint"] == "aabbccdd11223344"


async def test_retry_on_419_or_403() -> None:
    """Provider should invalidate session and retry once on HTTP 419 or 403."""
    expired_response = _make_fake_response(403)
    ok_post_response = _make_fake_response(200, {"job_id": "job123"})
    ok_get_response = _make_fake_response(200, {"status": "completed", "data": {"text": "done"}})
    
    fake_client = _make_fake_client([expired_response, ok_post_response], [ok_get_response])

    from rewrite_service.config import load_settings
    settings = load_settings()

    provider = CleverHumanizerProvider(settings)
    provider.session_manager.get_session = AsyncMock(
        side_effect=[_make_session(), _make_session()]
    )
    provider.session_manager.invalidate = AsyncMock()

    with patch("rewrite_service.providers.httpx.AsyncClient", return_value=fake_client):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await provider.rewrite(RewriteRequest(text="test"))

    assert result.text == "done"
    provider.session_manager.invalidate.assert_awaited_once()
