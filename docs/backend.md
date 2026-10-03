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

Available scenario names are `normal`, `local_disturbance`, `seiche`, and `sudden_surge`. Each run produces twelve readings for each of three nodes. `LUDINGTON-01` represents the physical node during the demo; the other nodes remain labeled as simulated.

## Live dashboard connection

Connect the dashboard to `ws://127.0.0.1:8000/ws/live`. Messages contain a `type` field and either a reading, an event, or a scenario completion summary.

## Tests

```bash
pytest -q
```

The current tests cover normal, surge, and oscillating signals; three-node correlation; and the Arduino serial protocol.
