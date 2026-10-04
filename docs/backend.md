# Backend development

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn backend.main:app --reload
```

Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

## Try the detection loop

Start a correlated seiche scenario:

```bash
curl -X POST http://127.0.0.1:8000/api/scenarios/seiche
```

Then inspect the latest event and node states:

```bash
curl http://127.0.0.1:8000/api/events/latest
curl http://127.0.0.1:8000/api/nodes
```

Available modes are `normal`, `local_disturbance`, `seiche`, `sudden_surge`, and `manual`, optionally centered with `?location=<node id>` (six nodes from Manistee to South Haven). A run seeds twelve readings per node so the detector reacts at once, then streams one reading per node per second until another mode starts. The Arduino feeds `LUDINGTON-01` only in `manual` mode; every other mode plays tray-shaped data for it. See [`dashboard-ibm.md`](dashboard-ibm.md) for the data sources.

## Arduino connection

Set `SERIAL_PORT` in `.env` to the Arduino device path (for example, `/dev/cu.usbmodem...` on macOS). The backend opens the port at `SERIAL_BAUD_RATE`, converts incoming distance readings using `REFERENCE_DISTANCE_CM`, and sends `STATE,SAFE`, `STATE,WATCH`, or `STATE,WARNING` when the network state changes. If the device is unplugged, the API keeps running and retries the connection. Leave `SERIAL_PORT` empty to run without hardware.

After the first reading on each connection, the backend sends `TIME,<unix_epoch>` to synchronize the Arduino clock. A physical reading more than 30 seconds off is stored with server receive time so it remains visible in recent readings. Arduino readings are paused while a demo mode other than `manual` plays. The alert board shows the status of the location chosen with `PUT /api/board` (default `LUDINGTON-01`): `STATE,SURGE` for a sudden-surge warning, otherwise `STATE,SAFE`, `WATCH`, or `WARNING`. `POST /api/sensor/calibrate` (manual mode, still water) resets the zero.

## Live dashboard connection

Connect the dashboard to `ws://127.0.0.1:8000/ws/live`. Messages contain a `type` field and either a reading, an event, or a scenario completion summary.

## Incident Replay with Tiger Data

Create a Tiger Data service and put its PostgreSQL connection URI in local `.env` as `TIGER_DATABASE_URL`. Keep the URI out of Git. Install dependencies with `pip install -r requirements-dev.txt`, then restart the backend. On startup the backend creates a TimescaleDB `readings` hypertable and ordinary `events` and `event_readings` tables. Every physical and simulated reading goes to the hypertable with its timestamp and source. When Python detects an event, the event and a frozen copy of its detector input window are committed together. Startup fails if the configured service cannot provide the hypertable; the dashboard will never claim Tiger Data is active when it is not. With Tiger Data configured, live readings are saved in batches on a background thread (one round trip per burst, never blocking the event loop or the alert board); events and their evidence windows are still committed together.

With `TIGER_DATABASE_URL` empty, the same replay API runs on local SQLite for development and labels itself "Local SQLite preview". Existing SQLite incidents are not copied into Tiger Data when switching storage. To inspect a stored incident, run `GET /api/events/{event_id}/replay`, click **Incident Replay** in the dashboard header, or select an event and click **Replay event**. The dashboard animates saved traces, shows the first ≥1 cm change per node, and displays the detector's warning rule. Saved source labels distinguish live Arduino readings from simulated neighbors. The IBM explanation endpoint receives the saved node source and change summary for that event.

For a mixed-source demo, start `manual` mode in the demo control page while the Arduino is connected. Move the water for at least twelve good readings, then click **Trigger simulated neighbors** (or `POST /api/sensor/neighbor-response`). This copies the observed Ludington waveform into two explicitly simulated neighbor responses and lets Python detect the shared pattern. It is a demonstration of correlation with simulated response nodes, not independent confirmation from physical sensors at those locations. Open the dashboard and click **Replay event** to review the saved evidence. With only the physical disturbance and calm neighbors, the detector normally reports WATCH; with three abnormal correlated nodes it can report WARNING.

## Tests

```bash
pytest -q
```

The current tests cover normal, surge, and oscillating signals; three-node correlation; and the Arduino serial protocol.
