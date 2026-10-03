# WaveGuard Orchestrate agent

Optional. Set this up only after the direct Granite explanation works in the dashboard.

## Agent instructions

Paste the following into the agent's **Instructions** field in watsonx Orchestrate:

```text
You are the WaveGuard shoreline operations assistant for the eastern shore of Lake Michigan
(Ludington, Muskegon, Holland).

Always call getSituationReport before answering a question about current conditions.
To explain an event, call explainEvent with the event_id from getSituationReport,
getLatestEvent, or listEvents, and relay its summary, evidence, and recommended actions.

Rules:
- Severity (safe, watch, warning) and classification come only from the tools. Never change,
  soften, or escalate them, and never guess them when a tool fails.
- Report only values the tools return. Do not invent readings, times, or locations.
- Always say when a node is simulated. LUDINGTON-01 is the only physical sensor.
- A public warning returned by explainEvent is a draft. Say a human operator must approve it.
- If explainEvent fails or returns source "prerecorded", say that Granite was unavailable.
- You cannot trigger alarms, LEDs, buzzers, or scenarios.
```

## Setup

1. Start the backend: `uvicorn backend.main:app --port 8000`.
2. Expose it over HTTPS, for example `ngrok http 8000`.
3. Replace the `servers` URL in [`openapi.yaml`](openapi.yaml) with the tunnel URL.
4. In watsonx Orchestrate, open **Agent Builder → Tools → Add tool → OpenAPI** and import `openapi.yaml`. Select all four operations.
5. Create an agent named **WaveGuard Operations**, paste the instructions above, and attach the tools.
6. Run a scenario from the dashboard, then test the prompts below.

## Test prompts

| Prompt | Expected tool calls |
| --- | --- |
| What is happening on the shoreline right now? | `getSituationReport` |
| Explain the latest event and what we should do. | `getSituationReport` or `getLatestEvent`, then `explainEvent` |
| Which nodes are real sensors? | `getSituationReport` |
| Show the last three events. | `listEvents` with `limit=3` |
