# Dashboard and IBM Granite integration

Owner: Aneesh (`aneesh-ibm`)

## Run the dashboard

The dashboard is static HTML/JS with Chart.js and Leaflet vendored under `frontend/assets/vendor/`, so it works without a CDN (only the map tiles need internet).

Serve it on port 5500, which the backend's CORS settings already allow:

```bash
python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

| URL | Use |
| --- | --- |
| `http://127.0.0.1:5500/` | Live backend at `http://127.0.0.1:8000` |
| `http://127.0.0.1:5500/?mock=1` | Mock data in the browser, no backend needed |
| `http://127.0.0.1:5500/?mock=1&physical=1` | Mock data plus a fake 1 Hz Arduino stream for `LUDINGTON-01` |
| `http://127.0.0.1:5500/?api=http://192.168.1.20:8000` | Backend on another machine |

If the backend is unreachable, the page shows a banner with **Retry** and **Use mock data**.

### Live updates

- The dashboard listens on `/ws/live` for `reading` and `scenario_complete` messages and reconnects automatically.
- While the socket is down it polls `/api/nodes`, `/api/readings/latest`, and `/api/events/latest` every 3 seconds and shows **Polling REST**.
- Scenario runs label all three nodes `simulated`. `LUDINGTON-01` shows `physical` only while Arduino readings arrive. When a node's source changes, its chart line restarts, matching the backend's fresh signal window.
- The backend sends `TIME,<epoch>` after the first physical reading and stores a badly skewed reading at server receive time. The chart also handles an unsynced stream directly, as shown in `?mock=1&physical=1`.
- When live sensor readings make the detector re-report a different event, the last Granite explanation stays visible with an "Explains earlier event" note. Starting a new scenario clears it.
- Network severity is the highest node severity, raised to the event severity for affected nodes while the event is still active (at least one affected node is not `safe`). A per-node seiche reading is `watch`; the correlated event makes it a network `warning`.

## Backend wiring (for `backend/main.py`)

The IBM routes live in `backend/routes/agent_tools.py`. Register them next to the other routers:

```python
from backend.routes import agent_tools, events, nodes, readings, scenarios

app.include_router(agent_tools.router)
```

Until this is added, the dashboard still works and shows **IBM Granite: Route missing**.

### Endpoints added

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/ibm/status` | Whether Granite credentials are configured, and the model ID |
| `POST` | `/api/events/{event_id}/explain` | Explain a stored event with Granite (`?refresh=true` bypasses the cache) |
| `GET` | `/api/ibm/example` | Saved response labeled `prerecorded`, for the fallback plan |
| `GET` | `/api/agent/situation` | Overall severity, nodes, and active event (Orchestrate tool) |

`POST /api/events/{event_id}/explain` returns:

```json
{
  "event_id": "evt-1a2b3c4d5e",
  "severity": "warning",
  "classification": "seiche_like",
  "source": "granite",
  "model_id": "ibm/granite-4-h-small",
  "generated_at": "2026-10-03T14:31:02Z",
  "explanation": {
    "summary": "…",
    "evidence": ["…"],
    "recommended_actions": ["…"],
    "public_warning": "…"
  }
}
```

`severity` and `classification` are copied from the stored event, never from the model. Failures return `{"detail": {"code": "...", "message": "..."}}` with these codes:

| Code | HTTP | Meaning |
| --- | --- | --- |
| `not_configured` | 503 | `WATSONX_API_KEY` or `WATSONX_PROJECT_ID` missing |
| `auth_failed` | 502 | IBM Cloud rejected the API key |
| `timeout` | 504 | watsonx.ai took longer than `WATSONX_TIMEOUT_SECONDS` (default 30) |
| `unreachable` / `request_failed` | 502 | Network or watsonx.ai error |
| `invalid_output` | 502 | Granite did not return the required JSON |

## Configure IBM watsonx.ai

1. In IBM Cloud, create or open a watsonx.ai project and note its **Project ID** (Manage → General).
2. Associate a Watson Machine Learning service with the project.
3. Create an IBM Cloud API key (Manage → Access (IAM) → API keys).
4. Fill in `.env` (never commit it):

   ```text
   WATSONX_API_KEY=...
   WATSONX_PROJECT_ID=...
   WATSONX_URL=https://us-south.ml.cloud.ibm.com
   WATSONX_MODEL_ID=ibm/granite-4-h-small
   ```

5. Restart the backend and check `GET /api/ibm/status` returns `"configured": true`.

The client (`backend/services/watsonx_client.py`) calls the watsonx.ai chat REST API directly with an IAM token, sends only the stored event plus node source labels, validates the JSON with Pydantic, and caches one explanation per event so repeated clicks during the demo do not call IBM again.
Displayed evidence always comes from the detector's event fields. When any affected node is simulated or its source is unknown, the backend labels the explanation as a demonstration and makes the public warning draft conditional on field verification. Granite still supplies recommended actions.

## Prompt and fallback files

| File | Purpose |
| --- | --- |
| `ibm/warning_prompt.md` | System prompt: use supplied facts only, never change severity, return the four-key JSON |
| `ibm/example_event.json` | Saved input and response used by `/api/ibm/example` |
| `ibm/openapi.yaml` | Orchestrate tool definitions (optional) |
| `ibm/agent_instructions.md` | Orchestrate agent instructions and setup (optional) |

## Demo behavior

- **Auto-explain warnings** (on by default) requests a Granite explanation as soon as a new `warning` event arrives.
- If Granite fails, the IBM panel shows the error and a hint, plus **Retry** and **Show prerecorded example**. The prerecorded response is visibly labeled. Detection, the map, the chart, and alerts keep working.
- The public warning is shown as a draft that requires operator approval.

## Tests

```bash
pytest tests/test_watsonx_client.py
```

These use a fake HTTP session and do not call IBM.
