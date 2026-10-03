// In-browser stand-in for the backend so the dashboard can run without the API.
// It mirrors the backend scenario shapes and response schemas from docs/api-contract.md.
(function () {
  const NODES = [
    ["LUDINGTON-01", "physical"],
    ["MUSKEGON-02", "simulated"],
    ["HOLLAND-03", "simulated"],
  ];
  const ALL_NODE_IDS = NODES.map(([nodeId]) => nodeId);

  // Expected detector output for each scenario, matching backend/routes/scenarios.py.
  const SCENARIO_RESULTS = {
    normal: { nodeSeverity: () => "safe", event: null },
    local_disturbance: {
      nodeSeverity: (nodeId) => (nodeId === "LUDINGTON-01" ? "watch" : "safe"),
      event: {
        classification: "local_disturbance",
        severity: "watch",
        confidence: 0.99,
        affected_nodes: ["LUDINGTON-01"],
        amplitude_cm: 6.928,
        period_seconds: 6.0,
        correlation_score: 0.0,
      },
    },
    seiche: {
      nodeSeverity: () => "watch",
      event: {
        classification: "seiche_like",
        severity: "warning",
        confidence: 0.99,
        affected_nodes: ALL_NODE_IDS,
        amplitude_cm: 6.062,
        period_seconds: 6.0,
        correlation_score: 1.0,
      },
    },
    sudden_surge: {
      nodeSeverity: () => "warning",
      event: {
        classification: "sudden_surge",
        severity: "warning",
        confidence: 0.83,
        affected_nodes: ALL_NODE_IDS,
        amplitude_cm: 8.4,
        period_seconds: null,
        correlation_score: 1.0,
      },
    },
  };

  const PRERECORDED = {
    summary:
      "All three monitored shoreline nodes are oscillating together with matching timing, consistent with a seiche-like movement of the lake surface. The detector rated this a warning because the motion is strong and highly correlated across the network rather than confined to one site.",
    evidence: [
      "Three of three nodes show abnormal oscillation: Ludington (physical sensor), Muskegon and Holland (simulated).",
      "Peak-to-trough amplitude reached 7.0 cm.",
      "Estimated oscillation period is 6.0 seconds in the scaled demonstration.",
      "Cross-node correlation score is 0.97, so the nodes are moving together.",
      "Detector confidence is 0.85.",
    ],
    recommended_actions: [
      "Notify beach and harbor staff at Ludington, Muskegon, and Holland of a possible seiche.",
      "Advise clearing piers, breakwalls, and the water's edge until levels stabilize.",
      "Confirm the Ludington physical sensor reading visually before public release.",
      "Keep monitoring for repeated rises and falls over the next cycles.",
      "Approve and publish the public advisory below if conditions persist.",
    ],
    public_warning:
      "Water levels along the Ludington, Muskegon, and Holland shoreline are rising and falling quickly. Stay off piers and breakwalls and keep away from the water's edge until officials say conditions are safe.",
  };

  function level(scenario, nodeIndex, step) {
    const baseline = 14.0 + nodeIndex * 0.3;
    const noise = (Math.random() - 0.5) * 0.08;
    if (scenario === "normal") return baseline + 0.15 * Math.sin((step * Math.PI) / 4) + noise;
    if (scenario === "local_disturbance") {
      return baseline + (nodeIndex === 0 ? 4.0 * Math.sin((step * Math.PI) / 3) : 0.1) + noise;
    }
    if (scenario === "seiche") return baseline + 3.5 * Math.sin((step * Math.PI) / 3) + noise;
    return baseline + Math.max(0, step - 5) * 1.4 + noise;
  }

  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function mockExplanation(event) {
    const places = event.affected_nodes.join(", ");
    const period =
      event.period_seconds == null ? "unavailable" : `${event.period_seconds.toFixed(1)} seconds`;
    const kind = event.classification.replace(/_/g, " ");
    const actions = {
      warning: [
        `Notify shoreline staff responsible for ${places}.`,
        "Advise clearing piers, breakwalls, and the water's edge.",
        "Confirm the physical sensor visually before public release.",
        "Approve and publish the public advisory if conditions persist.",
      ],
      watch: [
        `Check the sensor and conditions at ${places}.`,
        "Increase monitoring frequency for the next several minutes.",
        "Hold public messaging unless other nodes become abnormal.",
      ],
      safe: ["Continue routine monitoring."],
    };
    return {
      summary: `The detector classified a ${kind} event with ${event.severity} severity affecting ${places}.`,
      evidence: [
        `${event.affected_nodes.length} node(s) affected: ${places}.`,
        `Amplitude ${event.amplitude_cm.toFixed(2)} cm; period ${period}.`,
        `Correlation score ${event.correlation_score.toFixed(2)}; confidence ${Math.round(event.confidence * 100)}%.`,
      ],
      recommended_actions: actions[event.severity] || actions.safe,
      public_warning:
        event.severity === "warning"
          ? `Water levels near ${places} are changing quickly. Stay off piers and away from the water's edge until officials say it is safe.`
          : "No public warning is recommended at this time.",
    };
  }

  class MockApi {
    constructor() {
      this.readings = [];
      this.events = [];
      this.nodeSeverity = {};
      this.onMessage = () => {};
    }

    subscribe(onMessage, onStatus) {
      this.onMessage = onMessage;
      onStatus("mock");
    }

    async health() {
      return { status: "ok", service: "waveguard-mock" };
    }

    async ibmStatus() {
      return { configured: true, model_id: "mock (not IBM)", last_error: null };
    }

    async nodes() {
      const latest = new Map();
      for (const reading of this.readings) latest.set(reading.node_id, reading);
      return [...latest.values()].map((reading) => ({
        node_id: reading.node_id,
        source: reading.source,
        severity: this.nodeSeverity[reading.node_id] || "safe",
        last_reading: reading,
      }));
    }

    async latestReadings(limit) {
      return this.readings.slice(-limit).reverse();
    }

    async latestEvent() {
      return this.events.at(-1) || null;
    }

    async runScenario(scenario) {
      const spec = SCENARIO_RESULTS[scenario];
      if (!spec) throw new Error(`Unknown scenario ${scenario}`);
      await delay(250);

      const start = Date.now() - 11000;
      let generated = 0;
      for (let step = 0; step < 12; step += 1) {
        NODES.forEach(([nodeId, source], nodeIndex) => {
          this.readings.push({
            node_id: nodeId,
            timestamp: new Date(start + step * 1000).toISOString(),
            water_level_cm: Number(level(scenario, nodeIndex, step).toFixed(3)),
            quality: 0.98,
            source,
          });
          generated += 1;
        });
      }
      this.readings = this.readings.slice(-600);
      for (const nodeId of ALL_NODE_IDS) this.nodeSeverity[nodeId] = spec.nodeSeverity(nodeId);

      const event = spec.event && {
        event_id: `evt-mock${Math.random().toString(16).slice(2, 8)}`,
        ...spec.event,
        detected_at: new Date().toISOString(),
      };
      if (event) this.events.push(event);

      this.onMessage({ type: "scenario_complete", scenario, event });
      return { scenario, readings_generated: generated, event };
    }

    async explain(eventId) {
      const event = this.events.find((item) => item.event_id === eventId);
      if (!event) throw Object.assign(new Error("Event not found"), { status: 404 });
      await delay(1200);
      return {
        event_id: event.event_id,
        severity: event.severity,
        classification: event.classification,
        source: "mock",
        model_id: null,
        generated_at: new Date().toISOString(),
        explanation: mockExplanation(event),
      };
    }

    async example(eventId) {
      const event = this.events.find((item) => item.event_id === eventId);
      return {
        event_id: event ? event.event_id : "evt-example01",
        severity: event ? event.severity : "warning",
        classification: event ? event.classification : "seiche_like",
        source: "prerecorded",
        model_id: null,
        generated_at: new Date().toISOString(),
        explanation: PRERECORDED,
      };
    }
  }

  window.WaveGuardMock = { MockApi };
})();
