# Architecture decisions

## Responsibilities

- The backend calculates signal features, classifies events, correlates nodes, and assigns severity.
- The physical node reports distance and quality; it displays the state returned by the backend.
- Simulated nodes follow the same reading contract and are labeled as simulated.
- The dashboard presents measurements and decisions without recalculating them.
- IBM Granite explains structured event evidence, recommends actions, and drafts warnings. It does not change severity or fabricate measurements.

## End-to-end flow

1. Physical and simulated nodes submit readings.
2. The backend normalizes readings and stores recent history.
3. The detector extracts amplitude, rate of change, variability, direction changes, and period.
4. The correlator compares abnormal signals across nodes.
5. The risk engine publishes `safe`, `watch`, or `warning`.
6. WebSocket clients receive the updated readings and event.
7. The backend sends the new state to the physical node.
8. On request, Granite receives the finalized event object and returns an operator explanation.
