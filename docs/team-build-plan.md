# WaveGuard team specification and build plan

This document defines the technical scope, ownership, interfaces, build order, and completion criteria for the four-person WaveGuard team. Each person owns an end-to-end workstream, but every component follows the shared contracts in [`api-contract.md`](api-contract.md).

## 1. Project goal

WaveGuard demonstrates a distributed Great Lakes coastal hazard intelligence network. It combines one physical Arduino water-level node with simulated shoreline nodes to detect:

- Normal water movement
- A disturbance affecting only one sensor
- Seiche-like oscillation across multiple locations
- A sudden multi-node water-level surge
- Low-quality or faulty sensor data

The final demonstration must complete this path:

```text
Physical sensor and simulated nodes
                 |
                 v
        FastAPI ingestion layer
                 |
                 v
   Detection and multi-node correlation
          |                    |
          v                    v
 Live dashboard       IBM Granite explanation
          |
          v
 Arduino LEDs and warning buzzer
```

## 2. Definition of done

The hackathon MVP is complete when the team can demonstrate all of the following without editing code during the presentation:

1. The dashboard shows three or more named shoreline nodes.
2. At least one node receives real ultrasonic readings from an Arduino.
3. Other nodes are visibly labeled `simulated`.
4. A normal scenario remains `safe`.
5. A one-node disturbance produces a `watch` without a network-wide warning.
6. A correlated seiche scenario produces a `warning` affecting multiple nodes.
7. The dashboard updates without a page refresh.
8. IBM Granite explains the structured event evidence and suggests actions.
9. The physical green, yellow, and red indicators follow backend state.
10. A complete demonstration can be reset and repeated in under three minutes.

## 3. Shared technical decisions

### Stack

| Layer | Technology |
| --- | --- |
| Backend | Python, FastAPI, Pydantic |
| Storage | SQLite |
| Live updates | WebSocket |
| Signal processing | Python statistics, NumPy/SciPy when needed |
| Frontend | HTML, CSS, JavaScript, Chart.js, Leaflet |
| Physical node | Arduino Uno, ultrasonic sensor, LEDs, buzzer |
| AI explanation | IBM watsonx.ai with a Granite model |
| Optional agent workflow | IBM watsonx Orchestrate |

### Severity ownership

The deterministic backend assigns `safe`, `watch`, or `warning`. Granite explains that decision and recommends actions. Granite must not change severity, fabricate readings, or directly activate physical alerts.

### Required identifiers

Use these demo node identifiers consistently:

| Node | Source | Suggested location |
| --- | --- | --- |
| `LUDINGTON-01` | Physical | Ludington |
| `MUSKEGON-02` | Simulated | Muskegon |
| `HOLLAND-03` | Simulated | Holland |

## 4. Role A — Shanmuk: backend and system integration

**Branch:** `shanmuk-backend`

### Responsibilities

- Own the FastAPI application and shared Pydantic schemas.
- Accept physical and simulated readings through one interface.
- Calculate amplitude, rate of change, variability, trend, direction changes, and estimated period.
- Classify node behavior as normal, local disturbance, seiche-like, sudden surge, or sensor fault.
- Correlate abnormal behavior across nodes.
- Assign `safe`, `watch`, or `warning` severity.
- Store readings and detected events in SQLite.
- Broadcast readings and events over `/ws/live`.
- Parse Arduino serial readings and return alert-state commands.
- Coordinate final connections between all team components.

### Owned files

```text
backend/main.py
backend/config.py
backend/database.py
backend/schemas.py
backend/serial_reader.py
backend/realtime.py
backend/detection/
backend/routes/
backend/services/event_service.py
tests/test_detection.py
tests/test_correlation.py
tests/test_serial_reader.py
```

### Build order

1. Implement schemas and API health check.
2. Store and retrieve readings.
3. Extract per-node signal features.
4. Implement deterministic classification.
5. Correlate multiple nodes and assign severity.
6. Add event storage and retrieval.
7. Broadcast updates to WebSocket clients.
8. Parse physical serial readings and format state commands.
9. Connect dashboard, IBM service, and Arduino.

### Acceptance criteria

- `POST /api/readings` accepts the shared reading object.
- `/api/scenarios/seiche` generates a three-node warning.
- `/api/scenarios/normal` generates no hazard event.
- `/api/events/latest` returns the most recent stored event.
- `/api/nodes` returns source and state for every active node.
- All backend tests pass.

## 5. Role B — Aneesh: dashboard and IBM integration

**Branch:** `aneesh-ibm`

### Responsibilities

- Build the operator dashboard.
- Display a Great Lakes map with physical and simulated node labels.
- Plot live water-level readings for each node.
- Show classification, severity, confidence, correlation, and affected nodes.
- Provide scenario buttons for the repeatable demonstration.
- Connect to `/ws/live` for automatic updates.
- Integrate IBM watsonx.ai and a Granite model.
- Render Granite output as an explanation, evidence summary, recommended actions, and public-warning draft.
- Add a clear loading state and a useful error state when IBM is unavailable.
- Optionally expose backend OpenAPI operations as watsonx Orchestrate tools after the direct Granite integration works.

### Owned files

```text
frontend/index.html
frontend/styles.css
frontend/app.js
frontend/map.js
frontend/charts.js
frontend/assets/
backend/services/watsonx_client.py
backend/routes/agent_tools.py
ibm/openapi.yaml
ibm/agent_instructions.md
ibm/warning_prompt.md
ibm/example_event.json
```

### Required dashboard sections

1. Network summary with overall severity.
2. Node map with source and state indicators.
3. Live multi-series water-level chart.
4. Latest-event evidence panel.
5. IBM explanation and recommended-actions panel.
6. Scenario controls for normal, local disturbance, seiche, and sudden surge.
7. Connection and IBM-service status indicators.

### Granite input

Send the detected event as structured JSON. The prompt must tell Granite to use only supplied facts and return:

```json
{
  "summary": "Short operator explanation",
  "evidence": ["Observed factor one", "Observed factor two"],
  "recommended_actions": ["Action one", "Action two"],
  "public_warning": "Short public-facing warning draft"
}
```

### Acceptance criteria

- The dashboard initially works with mocked data.
- It then works with the shared backend endpoints without schema changes.
- Node source labels remain visible.
- A seiche scenario updates the map, chart, severity, and event panel.
- Granite produces valid structured output from a real backend event.
- Missing credentials or IBM downtime does not break the rest of the dashboard.

## 6. Role C — Mithun: Arduino and physical alert system

**Branch:** `mithun-ardunio`

The existing branch name uses `ardunio`; keep that spelling in Git commands unless the team intentionally renames it.

### Responsibilities

- Wire and test the ultrasonic sensor above a water tray.
- Sample distance at a stable interval.
- Reject impossible or timed-out measurements.
- Estimate reading quality.
- Emit the agreed serial reading format.
- Listen for backend state commands.
- Control green, yellow, and red LEDs.
- Activate the buzzer only for `WARNING`.
- Document the final pin assignments, reference distance, and physical setup.
- Provide a quick calibration and reset process for the demo.

### Owned files

```text
arduino/waveguard_node/waveguard_node.ino
docs/wiring.md
docs/hardware-calibration.md
```

### Serial interface

Arduino output:

```text
READING,<unix_timestamp>,<distance_cm>,<quality>
```

Backend commands:

```text
STATE,SAFE
STATE,WATCH
STATE,WARNING
```

### Suggested hardware states

| Backend state | Green LED | Yellow LED | Red LED | Buzzer |
| --- | --- | --- | --- | --- |
| `SAFE` | On | Off | Off | Off |
| `WATCH` | Off | On | Off | Off |
| `WARNING` | Off | Off | On | Pulsing |

### Build order

1. Read and print raw sensor distance.
2. Add timeout handling and quality scoring.
3. Emit the exact serial contract.
4. Wire and test each LED separately.
5. Parse the three state commands.
6. Add warning buzzer behavior.
7. Calibrate over the actual water tray.
8. Complete an end-to-end test with the backend.

### Acceptance criteria

- Readings are stable when the water is still.
- Raising the water decreases sensor distance.
- Invalid echoes do not appear as valid surges.
- All three backend commands produce the correct physical state.
- Unplugging or resetting the Arduino does not crash the backend.
- Wiring and calibration can be reproduced from the documentation.

## 7. Role D — Teammate 3: simulation, QA, research, and demo operations

**Suggested branch:** `simulation-demo` after the teammate confirms the name

Do not create this branch until the team agrees on the branch name and owner.

### Responsibilities

- Build repeatable simulation data for every scenario.
- Verify that simulations follow the same schema as physical readings.
- Research defensible Great Lakes seiche context for the README and presentation.
- Test API, dashboard, IBM, and hardware integration.
- Record expected results and discovered defects.
- Own the final demo script, timing, reset process, and fallback plan.
- Collect screenshots and a short backup recording after the full system works.
- Verify that simulated data is clearly disclosed.

### Owned files

```text
simulation/node_simulator.py
simulation/scenario_runner.py
simulation/scenarios/normal.json
simulation/scenarios/local_disturbance.json
simulation/scenarios/seiche.json
simulation/scenarios/sudden_surge.json
tests/fixtures/
docs/judging-metrics.md
docs/demo-script.md
docs/demo-checklist.md
```

### Scenario specifications

| Scenario | Expected node behavior | Expected result |
| --- | --- | --- |
| Normal | Small noise around a stable baseline | `safe`, no event |
| Local disturbance | One node moves sharply; others remain stable | `watch`, local disturbance |
| Seiche | Three nodes oscillate with related periods | `warning`, seiche-like event |
| Sudden surge | Multiple nodes rise quickly in the same direction | Multi-node surge warning |
| Sensor fault | Bad quality or impossible values at one node | Fault shown without network warning |

### Acceptance criteria

- Every scenario is repeatable from a single command or dashboard button.
- Expected results are written down and verified.
- Simulations include timestamps, source labels, and realistic baselines.
- The full demonstration runs twice consecutively after a reset.
- The team has a fallback path for unavailable hardware or IBM service.
- Claims used in the presentation have a source and do not overstate the prototype.

## 8. Shared integration checkpoints

### Checkpoint 1 — Contract test

- Each owner reads `docs/api-contract.md`.
- Mock reading and event JSON load in the backend and dashboard.
- Arduino owner confirms the serial message exactly.

### Checkpoint 2 — Simulation to backend

- Simulation submits readings to `POST /api/readings`.
- Backend returns node states and produces expected events.

### Checkpoint 3 — Backend to dashboard

- Dashboard loads nodes and recent readings.
- WebSocket updates appear without refreshing.
- Scenario buttons call the backend.

### Checkpoint 4 — Physical node

- Arduino replaces `LUDINGTON-01` simulated input.
- Backend converts measured distance into water level.
- Backend state reaches the physical indicators.

### Checkpoint 5 — IBM explanation

- Granite receives a stored event, not raw unvalidated sensor text.
- Structured output appears in the dashboard.
- An IBM failure produces a visible error without stopping detection.

### Checkpoint 6 — Full rehearsal

- Run normal, local disturbance, and seiche scenarios.
- Confirm dashboard, IBM response, and physical alert behavior.
- Reset and repeat the presentation flow.

## 9. Git workflow

Before starting work each day:

```bash
git fetch origin
git switch main
git pull origin main
git switch YOUR-BRANCH
git merge main
```

Before asking for review:

```bash
git status
git add <files-you-own>
git commit -m "Describe the completed feature"
git push origin YOUR-BRANCH
```

Rules:

- Do not commit `.env`, API keys, database files, or local virtual environments.
- Do not change shared schemas silently. Discuss and update `api-contract.md` first.
- Keep commits small enough to test and review.
- Pull `main` before every integration session.
- Merge working increments throughout the hackathon instead of waiting until the end.

## 10. Final demonstration ownership

| Demo segment | Owner |
| --- | --- |
| Problem and Great Lakes context | Simulation/demo owner |
| Physical water-tray interaction | Hardware owner |
| Detection and node correlation | Backend owner |
| Dashboard and IBM explanation | Frontend/IBM owner |
| Closing impact and expansion | Any designated final speaker |

The target presentation moment is:

> Start the seiche scenario, show multiple nodes oscillating, generate a correlated warning, display a Granite explanation, and activate the physical red LED and buzzer.

## 11. Fallback plan

- If the physical sensor fails, replay a previously recorded physical-node reading stream and disclose the fallback.
- If Granite is unavailable, show the stored event evidence and a saved example response labeled as prerecorded.
- If WebSocket updates fail, refresh data through the REST endpoints.
- If the buzzer cannot be used in the venue, demonstrate the red LED and dashboard warning.
- Keep a short screen recording of one successful end-to-end run.
