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

## Tests

```bash
pytest -q
```

The current tests cover normal, surge, and oscillating signals; three-node correlation; and the Arduino serial protocol.
