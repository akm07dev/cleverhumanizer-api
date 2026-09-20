# Cleverer Humanizer

A text humanization API. Send in text, get back a human-sounding rewrite.

**One endpoint. No API keys. No setup beyond install.**

---

## Quick Start

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
playwright install chromium
uvicorn rewrite_service.app:app --host 127.0.0.1 --port 8787
```

The server is now running at `http://127.0.0.1:8787`.

---

## Endpoints

### `POST /v1/rewrite`

Humanize a piece of text.

#### Request

```http
POST /v1/rewrite HTTP/1.1
Host: 127.0.0.1:8787
Content-Type: application/json

{
  "text": "It is important to note that this methodology utilizes approximately correct data.",
  "style": "casual",
  "type_generation": "humanize"
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | `string` | ✅ | — | The text to humanize (1 – 100,000 chars) |
| `style` | `string` | — | `"casual"` | Writing style for the output |
| `type_generation` | `string` | — | `"humanize"` | Generation mode |
| `html` | `string \| null` | — | `null` | Optional HTML version of the input |

#### Response `200 OK`

```json
{
  "text": "This approach uses roughly accurate data."
}
```

| Field | Type | Description |
|---|---|---|
| `text` | `string` | The rewritten text |

#### Error Responses

| Status | Meaning | Example |
|---|---|---|
| `422` | Validation error (empty text, too long, etc.) | `{"detail": [{"loc": ["body", "text"], ...}]}` |
| `502` | Upstream service failed or unreachable | `{"detail": "Upstream request failed: ..."}` |

---

### `GET /health`

Health check.

#### Response `200 OK`

```json
{
  "status": "ok"
}
```

---

## Configuration

Environment variables (all optional):

| Variable | Default | Description |
|---|---|---|
| `SESSION_TTL_SECONDS` | `1800` | Browser session cache lifetime in seconds |

---

## Examples

### PowerShell

```powershell
$body = @{ text = "It is important to note that this is approximately correct." } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8787/v1/rewrite -Method Post -ContentType "application/json" -Body $body
```

### curl

```bash
curl -X POST http://127.0.0.1:8787/v1/rewrite \
  -H "Content-Type: application/json" \
  -d '{"text": "It is important to note that this is approximately correct."}'
```

### Python (requests)

```python
import requests

response = requests.post(
    "http://127.0.0.1:8787/v1/rewrite",
    json={"text": "It is important to note that this is approximately correct."}
)
print(response.json()["text"])
```

### JavaScript (fetch)

```javascript
const response = await fetch("http://127.0.0.1:8787/v1/rewrite", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    text: "It is important to note that this is approximately correct."
  })
});
const data = await response.json();
console.log(data.text);
```

---

## License

Private use only.
