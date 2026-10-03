# WaveGuard

WaveGuard is a distributed Great Lakes coastal hazard intelligence network for detecting seiches and sudden water-level surges. One physical shoreline node is combined with clearly labeled simulated nodes so the system can distinguish a local disturbance or sensor fault from a broader event.

## Planned demo

1. Select a normal, local disturbance, seiche, or sudden-surge scenario.
2. Watch live water-level readings from one physical node and several simulated nodes.
3. Correlate abnormal behavior across nodes and assign `safe`, `watch`, or `warning` severity.
4. Ask IBM watsonx.ai Granite to explain the detected event and recommend actions.
5. Send the alert state to the Arduino LEDs and buzzer.

## Architecture

```text
Ultrasonic sensor -> Arduino -> USB serial -> FastAPI backend
Simulated nodes ---------------------------> FastAPI backend
                                               |
                                               +-> detector and node correlator
                                               +-> SQLite event history
                                               +-> live dashboard
                                               +-> IBM watsonx.ai Granite
                                               +-> Arduino alert state
```

The backend makes deterministic detection and severity decisions. Granite receives structured event evidence and produces explanations, recommended actions, and warning drafts. It does not override the detector or invent sensor facts.

## Repository layout

- `backend/` — API, schemas, detection, correlation, storage, and services
- `frontend/` — map, live charts, event panel, and scenario controls
- `arduino/` — physical sensor node and LED/buzzer controller
- `simulation/` — repeatable remote-node scenarios
- `ibm/` — Granite prompts and optional watsonx Orchestrate tool definitions
- `docs/` — architecture, API/serial contracts, and wiring notes
- `tests/` — detector and correlation fixtures

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn backend.main:app --reload
```

Open `http://127.0.0.1:8000/api/health` to verify the API.

## Shared contracts

Every component must follow [`docs/api-contract.md`](docs/api-contract.md). Agree on contract changes in `main` before implementing them in individual work branches.

## Team branches

Branches will be created after this shared scaffold is approved:

- `shanmuk-backend` — API, storage, detection, correlation, integration
- `frontend-ibm` — dashboard, Granite client, and optional Orchestrate tools
- `hardware` — Arduino node, alert outputs, and scenario simulation

Do not commit API keys or other secrets. Copy `.env.example` to `.env` for local configuration.
