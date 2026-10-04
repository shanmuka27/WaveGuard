# WaveGuard interface contract

All timestamps use ISO 8601 UTC in the API. Water level is measured in centimeters. Quality and confidence values range from `0.0` to `1.0`.

## Water-level reading

```json
{
  "node_id": "LUDINGTON-01",
  "timestamp": "2026-10-03T14:30:00Z",
  "water_level_cm": 14.72,
  "quality": 0.95,
  "source": "physical"
}
```

Allowed `source` values are `physical` and `simulated`. Simulated readings must remain visibly labeled in the dashboard.

## Detected event

```json
{
  "event_id": "evt-001",
  "classification": "seiche_like",
  "severity": "warning",
  "confidence": 0.87,
  "affected_nodes": ["LUDINGTON-01", "MUSKEGON-02", "HOLLAND-03"],
  "amplitude_cm": 5.4,
  "period_seconds": 18.2,
  "correlation_score": 0.82
}
```

Allowed classifications:

- `normal`
- `local_disturbance`
- `seiche_like`
- `sudden_surge`
- `sensor_fault`

Allowed severity values are `safe`, `watch`, and `warning`.

## HTTP and WebSocket interface

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Check backend availability |
| `GET` | `/api/nodes` | List node status and metadata |
| `POST` | `/api/readings` | Submit a physical or simulated reading |
| `GET` | `/api/readings/latest` | Retrieve recent readings |
| `GET` | `/api/events` | List detected events |
| `GET` | `/api/events/latest` | Retrieve the latest event |
| `POST` | `/api/scenarios/{scenario}` | Start a named demo scenario |
| `POST` | `/api/events/{event_id}/explain` | Generate a Granite explanation |
| `WS` | `/ws/live` | Stream readings, node state, and events |

## Arduino serial protocol

The Arduino sends:

```text
READING,<timestamp>,<distance_cm>,<quality>
```

The backend sends one of:

```text
STATE,SAFE
STATE,WATCH
STATE,WARNING
STATE,SURGE
TIME,<unix_epoch_seconds>
```

`STATE,SURGE` is a `warning` whose event classification is `sudden_surge`. `TIME` syncs the Arduino clock when the backend connects.

An ultrasonic sensor measures the distance from the mounted sensor to the water surface. Rising water decreases that distance. The backend converts it using a configured reference distance:

```text
water_level_cm = reference_distance_cm - distance_cm
```

The Arduino controls indicators from backend state: green for `SAFE`, yellow for `WATCH`, solid red plus buzzer for `WARNING`, and flashing red plus buzzer for `SURGE`.
