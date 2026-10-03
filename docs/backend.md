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

Available scenario names are `normal`, `local_disturbance`, `seiche`, and `sudden_surge`. Each run produces twelve simulated readings for each of three nodes. The Arduino supplies physical readings for `LUDINGTON-01` when connected.

## Arduino connection

Set `SERIAL_PORT` in `.env` to the Arduino device path (for example, `/dev/cu.usbmodem...` on macOS). The backend opens the port at `SERIAL_BAUD_RATE`, converts incoming distance readings using `REFERENCE_DISTANCE_CM`, and sends `STATE,SAFE`, `STATE,WATCH`, or `STATE,WARNING` when the network state changes. If the device is unplugged, the API keeps running and retries the connection. Leave `SERIAL_PORT` empty to run without hardware.

## Live dashboard connection

Connect the dashboard to `ws://127.0.0.1:8000/ws/live`. Messages contain a `type` field and either a reading, an event, or a scenario completion summary.

## Tests

```bash
pytest -q
```

The current tests cover normal, surge, and oscillating signals; three-node correlation; and the Arduino serial protocol.
