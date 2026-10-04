# WaveGuard

WaveGuard is a Great Lakes shoreline network that tells a local splash apart from a lake-wide seiche or sudden surge, and uses IBM Granite to explain every alert in plain language.

One physical node, an Arduino with an ultrasonic sensor over a water tray, works alongside five clearly labeled simulated nodes along Lake Michigan's eastern shore (Manistee to South Haven). A deterministic detector decides the alert; Granite only explains it.

## What it does

- **Measures water level** once per second from the physical sensor (`LUDINGTON-01`).
- **Detects and correlates.** Each node is classified from its signal: amplitude, rate of change, oscillation and period. One abnormal node is a local disturbance or sensor fault. Three or more correlated nodes oscillating is a seiche; rising together is a sudden surge.
- **Shows it live** on a one-screen dashboard: status strip, shoreline map, water-level chart, event evidence, event history and the Granite explanation.
- **Explains with IBM Granite** (watsonx.ai, `ibm/granite-4-h-small`): an operator summary, the evidence, recommended actions and a draft public warning. Granite never changes severity, and its text is labeled when the data is simulated.
- **Alerts physically.** The Arduino's LEDs and buzzer show the status of one chosen location:

| Status | Board |
| --- | --- |
| Safe | Green |
| Watch | Yellow |
| Warning (seiche) | Solid red, slow siren |
| Warning (sudden surge) | Flashing red, fast siren |

- **Keeps incident evidence** in a Tiger Data (TimescaleDB) hypertable, so any past event can be replayed with the exact readings the detector saw.

## Data, honestly labeled

| Data | Source |
| --- | --- |
| Ludington in **Manual** mode | The live tray sensor |
| Ludington in a demo scenario | Generated to match the tray sensor (same zero and range), labeled **Scenario** |
| Seiche and calm water at the other nodes | Real **NOAA** water-level records from the Ludington (9087023) and Holland (9087031) gauges, 2024; smoothed, rescaled to tray size, one 6-minute reading per second |
| Sudden surge and local disturbance | Synthetic. 6-minute gauge readings average sudden surges away, and no gauge records a splash |

Simulated nodes are labeled on the map, chart, event panel and in Granite's text. The dashboard states which data each scenario replays.

## Architecture

```text
Ultrasonic sensor -> Arduino UNO Q --USB serial--> FastAPI backend <--- admin page (scenarios,
Simulated nodes (NOAA replays) ------------------>      |                location, calibration)
                                                        +-> detector + node correlator
                                                        +-> Tiger Data hypertable (or SQLite)
                                                        +-> WebSocket -> live dashboard
                                                        +-> IBM watsonx.ai Granite
                                                        +-> STATE command -> LEDs and buzzer
```

## Run it (Windows)

```bash
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
copy .env.example .env
```

Fill in `.env`; never commit it:

- `WATSONX_API_KEY`, `WATSONX_PROJECT_ID`: IBM watsonx.ai, for Granite explanations
- `SERIAL_PORT`: the Arduino's port, e.g. `COM3` (leave empty to run without hardware)
- `TIGER_DATABASE_URL`: optional; without it, storage falls back to local SQLite

Then double-click **`start-demo.bat`**, or **`start-demo-phone.bat`** to also control it from a phone on the same network.

- Dashboard: <http://127.0.0.1:5500/>
- Demo control: <http://127.0.0.1:5500/admin.html>. Pick a location and a mode (keys 1–5: Normal, Local disturbance, Seiche, Sudden surge, Manual). It also has a Calibrate zero button and a raw sensor view.
- No backend or hardware: <http://127.0.0.1:5500/?mock=1> runs the dashboard on mock data.

On macOS or Linux, run `uvicorn backend.main:app` and `python scripts/serve_frontend.py` instead of the batch file.

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q
```

41 tests cover detection, correlation, scenarios, the serial protocol, the board logic, the Granite client and incident replay.

## Repository layout

- `backend/`: FastAPI app, detector and correlator, scenarios and NOAA replays, serial bridge, storage (SQLite or Tiger Data), Granite client
- `frontend/`: dashboard (`index.html`) and demo control page (`admin.html`)
- `arduino/waveguard_node/`: sensor and alert-board sketch (Arduino UNO Q; also builds for a classic Uno)
- `ibm/`: Granite prompt, saved example, watsonx Orchestrate tool definitions
- `docs/`: [API and serial contract](docs/api-contract.md), [backend](docs/backend.md), [dashboard and IBM](docs/dashboard-ibm.md), [wiring](docs/wiring.md), [calibration](docs/hardware-calibration.md), [team plan](docs/team-build-plan.md)
- `scripts/`: demo launcher and no-cache dashboard server

## Team

- Shanmuk: backend, detection, storage and integration
- Aneesh: dashboard and IBM Granite integration
- Mithun: Arduino node, wiring and calibration
