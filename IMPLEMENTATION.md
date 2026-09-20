# Implementation Details

> **Internal document.** For the public API reference, see [README.md](README.md).

---

## Architecture

```
POST /v1/rewrite { "text": "..." }
      │
      ▼
   FastAPI ──► CleverHumanizerProvider
                     │
                SessionManager (cached with TTL)
                     │
           ┌─── cached? ───┐
          yes               no
           │                │
           │     Playwright launches headless Chromium
           │     → loads cleverhumanizer.ai
           │     → intercepts POST /fingerprint-init
           │     → captures csrf, fingerprint, guest token, cookies
           │                │
           └──── use ◄──────┘
                  │
           httpx POST cleverhumanizer.ai/rewrite
                  │
                  ▼
           { "text": "...", "text2": "..." }
```

## Upstream Authentication

The upstream site (cleverhumanizer.ai) requires three custom headers on every API call. These are obtained by loading the real frontend in a headless browser:

### 1. `X-CSRF-TOKEN`

Fetched from `GET /csrf-token` by the frontend's `csrf.min.js`. Returns:

```json
{ "token": "<40-char token>", "authenticated": false }
```

The token value is sent as-is in the `X-CSRF-TOKEN` header.

### 2. `X-Guest-Access-Token`

Generated client-side by `csrf.min.js`:

```
32 random bytes → base64 → base64url → strip padding
```

Produces a 43-character string. Python equivalent:

```python
import os, base64
token = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
```

We capture whatever the frontend generates, but if the intercepted request doesn't include it, we generate one ourselves using the same algorithm.

### 3. `X-Client-Fingerprint`

A 32-character hex string produced by FingerprintJS 3.4.2 (`client-id.js`). It depends on browser canvas, WebGL, fonts, and platform characteristics — cannot be replicated outside a browser.

This is why we use Playwright: let the real frontend compute the fingerprint, then intercept the `POST /fingerprint-init` request to capture it.

## Session Lifecycle

1. **Bootstrap** — Playwright launches headless Chromium, navigates to `cleverhumanizer.ai`, and waits for the `POST /fingerprint-init` request.
2. **Capture** — All three headers and session cookies are extracted from the intercepted request.
3. **Cache** — The session is stored in memory for `SESSION_TTL_SECONDS` (default 30 min).
4. **Reuse** — Subsequent `/v1/rewrite` calls use the cached session.
5. **Refresh** — On TTL expiry or HTTP 419/429, the session is invalidated and a new one is bootstrapped.

## Upstream Request Flow

With a valid session, each rewrite call does:

```http
POST https://cleverhumanizer.ai/rewrite
Content-Type: application/json
X-CSRF-TOKEN: <token>
X-Guest-Access-Token: <token>
X-Client-Fingerprint: <fingerprint>
Cookie: XSRF-TOKEN=...; clever_ai_humanizer_session=...; aih_guest=...

{"text": "...", "style": "casual", "type_generation": "humanize"}
```

## Retry Logic

If the upstream returns HTTP 419 (CSRF expired) or 429 (rate limited):

1. The current session is invalidated
2. A fresh session is bootstrapped via Playwright
3. The request is retried **once**
4. If it fails again, a `502 Bad Gateway` is returned to the caller

## Project Structure

```
rewrite_service/
├── app.py          # FastAPI — single POST /v1/rewrite endpoint
├── config.py       # SESSION_TTL_SECONDS from environment
├── models.py       # RewriteRequest + RewriteResponse (Pydantic)
├── providers.py    # CleverHumanizerProvider — upstream proxy with retry
└── session.py      # Playwright bootstrap + SessionManager cache

tests/
├── test_api.py     # Provider + endpoint tests (mocked upstream)
└── test_session.py # Session manager + token generation tests
```

## Module Responsibilities

| Module | Purpose |
|---|---|
| `app.py` | FastAPI app, CORS, single `/v1/rewrite` route, error handling |
| `config.py` | Loads `SESSION_TTL_SECONDS` from environment |
| `models.py` | `RewriteRequest` (input validation) and `RewriteResponse` (output shape) |
| `providers.py` | `CleverHumanizerProvider` — builds headers/cookies, calls upstream, handles retry |
| `session.py` | `CleverSession` dataclass, `bootstrap_session()` via Playwright, `SessionManager` TTL cache |
