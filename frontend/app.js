// WaveGuard operator dashboard.
// Query parameters: ?api=http://host:8000 to point at another backend, ?mock=1 to use mock data.
(function () {
  const params = new URLSearchParams(window.location.search);
  const API_BASE_URL = (params.get("api") || "http://127.0.0.1:8000").replace(/\/+$/, "");
  const WS_URL = `${API_BASE_URL.replace(/^http/, "ws")}/ws/live`;

  const SCENARIO_READING_COUNT = 36; // 12 steps x 3 nodes, see backend/routes/scenarios.py
  const MAX_POINTS_PER_NODE = 120;
  const POLL_INTERVAL_MS = 3000;
  const NODES_REFRESH_DEBOUNCE_MS = 400;

  const SEVERITY_RANK = { unknown: -1, safe: 0, watch: 1, warning: 2 };
  const CLASSIFICATION_LABELS = {
    normal: "Normal",
    local_disturbance: "Local disturbance",
    seiche_like: "Seiche-like oscillation",
    sudden_surge: "Sudden surge",
    sensor_fault: "Sensor fault",
  };
  const NODE_META = {
    "LUDINGTON-01": { location: "Ludington", lat: 43.9553, lng: -86.4526, color: "#4fd1e8" },
    "MUSKEGON-02": { location: "Muskegon", lat: 43.2342, lng: -86.2484, color: "#b69cff" },
    "HOLLAND-03": { location: "Holland", lat: 42.7725, lng: -86.2119, color: "#ff8fb8" },
  };

  const state = {
    mode: params.get("mock") === "1" ? "mock" : "live",
    backend: "checking", // checking | online | offline
    stream: "connecting", // connecting | live | offline | mock
    ibm: { state: "unknown", modelId: null, message: null }, // unknown | ready | not_configured | missing | error | mock
    nodes: new Map(),
    series: new Map(),
    event: null,
    explanation: null,
    explainState: "idle", // idle | loading | done | error
    explainError: null,
    lastAutoExplainSignature: null,
    runningScenario: null,
    lastScenario: null,
    lastUpdate: null,
  };

  // ---------- Helpers ----------

  function h(tag, props = {}, ...children) {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value == null || value === false) continue;
      if (key === "class") element.className = value;
      else if (key === "text") element.textContent = value;
      else if (key.startsWith("on")) element.addEventListener(key.slice(2), value);
      else element.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child == null || child === false) continue;
      element.append(child instanceof Node ? child : String(child));
    }
    return element;
  }

  const $ = (id) => document.getElementById(id);
  const maxSeverity = (severities) =>
    severities.reduce((worst, s) => (SEVERITY_RANK[s] > SEVERITY_RANK[worst] ? s : worst), "unknown");
  const formatTime = (value) =>
    value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
  const eventSignature = (event) =>
    event ? `${event.classification}|${[...event.affected_nodes].sort().join(",")}|${event.severity}` : null;

  function sourceTag(source) {
    if (source === "physical") return h("span", { class: "tag physical", text: "Physical" });
    if (source === "simulated") return h("span", { class: "tag simulated", text: "Simulated" });
    return h("span", { class: "tag unknown-source", text: "No data" });
  }

  function severityBadge(severity) {
    return h("span", { class: `badge ${severity}`, text: severity === "unknown" ? "No data" : severity });
  }

  // ---------- Backend API ----------

  class HttpApi {
    constructor(baseUrl) {
      this.baseUrl = baseUrl;
      this.retryMs = 1000;
    }

    async request(path, { method = "GET", timeoutMs = 6000 } = {}) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      let response;
      try {
        response = await fetch(this.baseUrl + path, {
          method,
          headers: { Accept: "application/json" },
          signal: controller.signal,
        });
      } catch (error) {
        const timedOut = error.name === "AbortError";
        throw Object.assign(new Error(timedOut ? "Request timed out" : "Backend unreachable"), {
          code: timedOut ? "timeout" : "unreachable",
          network: true,
        });
      } finally {
        clearTimeout(timer);
      }

      const body = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = body && body.detail;
        const message =
          typeof detail === "string" ? detail : (detail && detail.message) || `HTTP ${response.status}`;
        throw Object.assign(new Error(message), {
          status: response.status,
          code: detail && detail.code,
        });
      }
      return body;
    }

    health() {
      return this.request("/api/health", { timeoutMs: 3000 });
    }

    ibmStatus() {
      return this.request("/api/ibm/status");
    }

    nodes() {
      return this.request("/api/nodes");
    }

    latestReadings(limit) {
      return this.request(`/api/readings/latest?limit=${limit}`);
    }

    async latestEvent() {
      try {
        return await this.request("/api/events/latest");
      } catch (error) {
        if (error.status === 404) return null;
        throw error;
      }
    }

    runScenario(scenario) {
      return this.request(`/api/scenarios/${encodeURIComponent(scenario)}`, {
        method: "POST",
        timeoutMs: 15000,
      });
    }

    explain(eventId, refresh) {
      const query = refresh ? "?refresh=true" : "";
      return this.request(`/api/events/${encodeURIComponent(eventId)}/explain${query}`, {
        method: "POST",
        timeoutMs: 60000,
      });
    }

    example(eventId) {
      return this.request(`/api/ibm/example?event_id=${encodeURIComponent(eventId || "")}`);
    }

    subscribe(onMessage, onStatus) {
      const scheduleReconnect = () => {
        setTimeout(connect, this.retryMs);
        this.retryMs = Math.min(this.retryMs * 2, 15000);
      };
      const connect = () => {
        onStatus("connecting");
        let socket;
        try {
          socket = new WebSocket(WS_URL);
        } catch (error) {
          onStatus("offline");
          scheduleReconnect();
          return;
        }
        socket.onopen = () => {
          this.retryMs = 1000;
          onStatus("live");
        };
        socket.onmessage = (message) => {
          try {
            onMessage(JSON.parse(message.data));
          } catch (error) {
            console.warn("Ignoring malformed live message", error);
          }
        };
        socket.onclose = () => {
          onStatus("offline");
          scheduleReconnect();
        };
      };
      connect();
    }
  }

  const api = state.mode === "mock" ? new window.WaveGuardMock.MockApi() : new HttpApi(API_BASE_URL);

  // ---------- Derived state ----------

  // An event counts only while at least one of its nodes is still abnormal,
  // matching GET /api/agent/situation on the backend.
  function isEventActive(event = state.event) {
    if (!event) return false;
    return event.affected_nodes.some((nodeId) => {
      const node = state.nodes.get(nodeId);
      return node && node.severity !== "safe";
    });
  }

  function effectiveSeverity(nodeId) {
    const node = state.nodes.get(nodeId);
    if (!node) return "unknown";
    if (isEventActive() && state.event.affected_nodes.includes(nodeId)) {
      return maxSeverity([node.severity, state.event.severity]);
    }
    return node.severity;
  }

  function overallSeverity() {
    if (!state.nodes.size) return "unknown";
    return maxSeverity([...state.nodes.keys()].map(effectiveSeverity));
  }

  function orderedNodeIds() {
    const known = Object.keys(NODE_META);
    const extra = [...state.nodes.keys()].filter((id) => !known.includes(id)).sort();
    return [...known, ...extra];
  }

  // ---------- Data updates ----------

  function touch() {
    state.lastUpdate = new Date();
  }

  function addReading(reading) {
    let entry = state.series.get(reading.node_id);
    if (!entry) {
      entry = { source: reading.source, points: [] };
      state.series.set(reading.node_id, entry);
    }
    entry.source = reading.source;
    entry.points.push({ x: Date.parse(reading.timestamp), y: reading.water_level_cm });
    entry.points.sort((a, b) => a.x - b.x);
    if (entry.points.length > MAX_POINTS_PER_NODE) {
      entry.points.splice(0, entry.points.length - MAX_POINTS_PER_NODE);
    }

    const node = state.nodes.get(reading.node_id);
    if (node) node.last_reading = reading;
    else state.nodes.set(reading.node_id, { node_id: reading.node_id, source: reading.source, severity: "safe", last_reading: reading });
  }

  async function reloadReadings(limit = SCENARIO_READING_COUNT) {
    const readings = await api.latestReadings(limit);
    state.series.clear();
    readings
      .slice()
      .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp))
      .forEach(addReading);
  }

  async function refreshNodes() {
    const nodes = await api.nodes();
    state.nodes = new Map(nodes.map((node) => [node.node_id, node]));
  }

  let nodesRefreshTimer = null;
  function scheduleNodesRefresh() {
    clearTimeout(nodesRefreshTimer);
    nodesRefreshTimer = setTimeout(async () => {
      try {
        await refreshNodes();
        render();
      } catch (error) {
        handleBackendError(error);
      }
    }, NODES_REFRESH_DEBOUNCE_MS);
  }

  function setEvent(event, { fromLive = false } = {}) {
    const previous = state.event;
    if (previous && event && previous.event_id === event.event_id) return;

    state.event = event || null;
    // Keep the current explanation when the detector re-reports the same situation.
    if (eventSignature(previous) !== eventSignature(state.event)) {
      state.explanation = null;
      state.explainState = "idle";
      state.explainError = null;
    }

    const shouldAutoExplain =
      fromLive &&
      event &&
      event.severity === "warning" &&
      $("auto-explain").checked &&
      eventSignature(event) !== state.lastAutoExplainSignature &&
      !["not_configured", "missing"].includes(state.ibm.state);
    if (shouldAutoExplain) {
      state.lastAutoExplainSignature = eventSignature(event);
      explain();
    }
  }

  async function refreshAll({ live = false } = {}) {
    const [nodes, readings, event] = await Promise.all([
      api.nodes(),
      api.latestReadings(SCENARIO_READING_COUNT),
      api.latestEvent(),
    ]);
    state.nodes = new Map(nodes.map((node) => [node.node_id, node]));
    state.series.clear();
    readings
      .slice()
      .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp))
      .forEach(addReading);
    setEvent(event, { fromLive: live });
    setBackend("online");
    touch();
  }

  async function refreshIbmStatus() {
    if (state.mode === "mock") {
      state.ibm = { state: "mock", modelId: null, message: "Mock explanations are generated locally." };
      return;
    }
    try {
      const status = await api.ibmStatus();
      state.ibm = {
        state: status.configured ? "ready" : "not_configured",
        modelId: status.model_id,
        message: status.last_error,
      };
    } catch (error) {
      state.ibm =
        error.status === 404
          ? { state: "missing", modelId: null, message: "The backend has not registered the IBM routes yet." }
          : { state: "error", modelId: null, message: error.message };
    }
  }

  function setBackend(status) {
    state.backend = status;
    $("offline-banner").hidden = status !== "offline" || state.mode === "mock";
  }

  function handleBackendError(error) {
    if (error && error.network) setBackend("offline");
    console.warn(error);
    render();
  }

  function handleLiveMessage(message) {
    switch (message.type) {
      case "reading":
        if (message.reading) addReading(message.reading);
        if (message.event) setEvent(message.event, { fromLive: true });
        scheduleNodesRefresh();
        break;
      case "scenario_complete":
        setEvent(message.event, { fromLive: true });
        Promise.all([reloadReadings(), refreshNodes()])
          .then(render)
          .catch(handleBackendError);
        break;
      case "event":
        if (message.event) setEvent(message.event, { fromLive: true });
        scheduleNodesRefresh();
        break;
      default:
        return;
    }
    setBackend("online");
    touch();
    render();
  }

  // ---------- Actions ----------

  async function runScenario(scenario) {
    if (state.runningScenario) return;
    state.runningScenario = scenario;
    $("scenario-status").textContent = `Running ${scenario.replace(/_/g, " ")}…`;
    render();
    try {
      const result = await api.runScenario(scenario);
      setEvent(result.event, { fromLive: true });
      await Promise.all([reloadReadings(result.readings_generated || SCENARIO_READING_COUNT), refreshNodes()]);
      state.lastScenario = scenario;
      setBackend("online");
      touch();
      const outcome = result.event
        ? `${CLASSIFICATION_LABELS[result.event.classification] || result.event.classification} · ${result.event.severity}`
        : "no hazard event";
      $("scenario-status").textContent = `${scenario.replace(/_/g, " ")} complete: ${outcome}.`;
    } catch (error) {
      $("scenario-status").textContent = `Scenario failed: ${error.message}`;
      handleBackendError(error);
    } finally {
      state.runningScenario = null;
      render();
    }
  }

  async function explain(refresh = false) {
    const event = state.event;
    if (!event) return;
    state.explainState = "loading";
    state.explainError = null;
    render();
    try {
      const result = await api.explain(event.event_id, refresh);
      if (!state.event || state.event.event_id !== event.event_id) return;
      state.explanation = result;
      state.explainState = "done";
      if (state.mode !== "mock") state.ibm = { ...state.ibm, state: "ready", message: null };
    } catch (error) {
      if (!state.event || state.event.event_id !== event.event_id) return;
      state.explainState = "error";
      state.explainError = { code: error.code || (error.status ? `http_${error.status}` : "error"), message: error.message };
      if (error.code === "not_configured") state.ibm = { ...state.ibm, state: "not_configured", message: error.message };
      else if (error.status === 404 && error.message === "Not Found") state.ibm = { ...state.ibm, state: "missing" }; // FastAPI default: route not registered
      else if (!error.network) state.ibm = { ...state.ibm, state: "error", message: error.message };
      if (error.network) setBackend("offline");
    } finally {
      render();
    }
  }

  async function showPrerecorded() {
    try {
      state.explanation = await api.example(state.event && state.event.event_id);
      state.explainState = "done";
    } catch (error) {
      state.explainError = { code: "prerecorded_unavailable", message: `Prerecorded example unavailable: ${error.message}` };
      state.explainState = "error";
    }
    render();
  }

  // ---------- Rendering ----------

  const STATUS_VIEWS = {
    backend: {
      checking: ["pending", "Checking…"],
      online: ["ok", "Online"],
      offline: ["bad", "Offline"],
    },
    stream: {
      connecting: ["pending", "Connecting…"],
      live: ["ok", "Connected"],
      offline: ["pending", "Polling REST"],
      mock: ["info", "Mock"],
    },
    ibm: {
      unknown: ["", "—"],
      ready: ["ok", "Ready"],
      not_configured: ["bad", "Not configured"],
      missing: ["bad", "Route missing"],
      error: ["bad", "Unavailable"],
      mock: ["info", "Mock"],
    },
  };

  function setStatus(id, [tone, text], title) {
    const element = $(id);
    element.dataset.tone = tone;
    element.querySelector(".value").textContent = text;
    element.title = title || "";
  }

  function renderStatus() {
    if (state.mode === "mock") setStatus("status-backend", ["info", "Mock"], "Running without the backend");
    else setStatus("status-backend", STATUS_VIEWS.backend[state.backend], API_BASE_URL);
    setStatus("status-stream", STATUS_VIEWS.stream[state.stream] || ["", "—"], WS_URL);
    setStatus("status-ibm", STATUS_VIEWS.ibm[state.ibm.state], state.ibm.message || state.ibm.modelId || "");
    setStatus(
      "status-mode",
      state.mode === "mock" ? ["info", "Mock data"] : ["ok", "Live backend"],
      state.mode === "mock" ? "Remove ?mock=1 to use the backend" : ""
    );
  }

  function renderSummary() {
    const overall = overallSeverity();
    $("summary").dataset.severity = overall;
    $("overall-severity").textContent = overall === "unknown" ? "—" : overall;

    let text;
    if (!state.nodes.size) {
      text = state.backend === "offline" && state.mode !== "mock" ? "Backend offline. No live data." : "Waiting for readings…";
    } else if (isEventActive()) {
      const event = state.event;
      const label = CLASSIFICATION_LABELS[event.classification] || event.classification;
      text = `${label} affecting ${event.affected_nodes.length} node${event.affected_nodes.length === 1 ? "" : "s"}: ${event.affected_nodes.join(", ")}.`;
    } else if (overall === "safe") {
      text = `All ${state.nodes.size} reporting nodes are within normal range.`;
    } else {
      text = "Abnormal readings at one or more nodes.";
    }
    $("summary-text").textContent = text;

    const nodes = [...state.nodes.values()];
    $("stat-nodes").textContent = nodes.length;
    $("stat-physical").textContent = nodes.filter((node) => node.source === "physical").length;
    $("stat-simulated").textContent = nodes.filter((node) => node.source === "simulated").length;
    $("stat-updated").textContent = formatTime(state.lastUpdate);
  }

  function renderScenarios() {
    document.querySelectorAll("[data-scenario]").forEach((button) => {
      const scenario = button.dataset.scenario;
      button.disabled = Boolean(state.runningScenario) || (state.mode !== "mock" && state.backend === "offline");
      button.setAttribute("aria-busy", String(state.runningScenario === scenario));
      button.classList.toggle("active", state.lastScenario === scenario);
    });
  }

  let mapView = null;
  let chartView = null;

  function renderNodes() {
    const rows = orderedNodeIds().map((nodeId) => {
      const node = state.nodes.get(nodeId);
      return {
        node_id: nodeId,
        source: node ? node.source : null,
        severity: effectiveSeverity(nodeId),
        level: node && node.last_reading ? node.last_reading.water_level_cm : null,
      };
    });
    mapView.update(rows);

    $("node-list").replaceChildren(
      ...rows.map((row) =>
        h(
          "li",
          { class: "node-row" },
          h("span", { class: "swatch", style: `background:${(NODE_META[row.node_id] || {}).color || "#5d7b8a"}` }),
          h(
            "span",
            {},
            h("span", { class: "node-name", text: row.node_id }),
            " ",
            h("span", { class: "muted small", text: (NODE_META[row.node_id] || {}).location || "" })
          ),
          sourceTag(row.source),
          h(
            "span",
            { class: "node-level" },
            row.level == null ? "—" : `${row.level.toFixed(2)} cm`,
            " ",
            severityBadge(row.severity)
          )
        )
      )
    );
  }

  function renderChart() {
    const series = new Map(
      orderedNodeIds()
        .filter((nodeId) => state.series.has(nodeId))
        .map((nodeId) => [nodeId, state.series.get(nodeId)])
    );
    chartView.setSeries(series);
    $("chart-empty").hidden = series.size > 0;
  }

  function metric(label, value, fraction) {
    return h(
      "div",
      { class: "metric" },
      h("dt", { text: label }),
      h("dd", { text: value }),
      fraction == null
        ? null
        : h("div", { class: "meter" }, h("span", { style: `width:${Math.round(Math.max(0, Math.min(1, fraction)) * 100)}%` }))
    );
  }

  function renderEvent() {
    const body = $("event-body");
    const event = state.event;
    if (!event) {
      body.replaceChildren(
        h(
          "div",
          { class: "empty-state" },
          h("strong", { text: "No hazard event" }),
          state.lastScenario ? "The latest scenario produced no detector event." : "Run a scenario or wait for live readings."
        )
      );
      return;
    }

    const active = isEventActive(event);
    body.replaceChildren(
      h(
        "div",
        { class: "event-header" },
        h("h3", { text: CLASSIFICATION_LABELS[event.classification] || event.classification }),
        severityBadge(event.severity),
        active ? null : h("span", { class: "chip", text: "Resolved — nodes now safe" })
      ),
      h(
        "dl",
        { class: "metrics" },
        metric("Confidence", `${Math.round(event.confidence * 100)}%`, event.confidence),
        metric("Correlation", event.correlation_score.toFixed(2), event.correlation_score),
        metric("Amplitude", `${event.amplitude_cm.toFixed(2)} cm`),
        metric("Period", event.period_seconds == null ? "—" : `${event.period_seconds.toFixed(1)} s`)
      ),
      h("p", { class: "eyebrow", text: `Affected nodes (${event.affected_nodes.length})` }),
      h(
        "ul",
        { class: "affected" },
        event.affected_nodes.map((nodeId) => {
          const node = state.nodes.get(nodeId);
          return h("li", {}, nodeId, sourceTag(node ? node.source : null));
        })
      ),
      h("p", { class: "event-meta", text: `${event.event_id} · detected ${formatTime(event.detected_at)}` })
    );
  }

  function explanationView(result) {
    const sourceTagView = {
      granite: h("span", { class: "tag", text: "IBM Granite" }),
      prerecorded: h("span", { class: "tag prerecorded", text: "Prerecorded example" }),
      mock: h("span", { class: "tag mock", text: "Mock — not IBM" }),
    }[result.source] || h("span", { class: "tag", text: result.source });

    const note = {
      prerecorded: "Granite was unavailable. This saved response is shown for demonstration only.",
      mock: "Generated in the browser from the event fields.",
    }[result.source];

    const explanation = result.explanation;
    const copyButton = h("button", { type: "button", class: "button small ghost", text: "Copy draft" });
    copyButton.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(explanation.public_warning);
        copyButton.textContent = "Copied";
      } catch (error) {
        copyButton.textContent = "Copy failed";
      }
      setTimeout(() => (copyButton.textContent = "Copy draft"), 1500);
    });

    return [
      h(
        "p",
        { class: "source-label" },
        sourceTagView,
        result.model_id ? h("span", { class: "chip", text: result.model_id }) : null,
        h("span", { text: `for ${result.event_id} · ${formatTime(result.generated_at)}` }),
        note ? h("span", { text: note }) : null
      ),
      h(
        "div",
        { class: "explanation" },
        h("section", {}, h("h3", { text: "Operator summary" }), h("p", { class: "summary-copy", text: explanation.summary })),
        h(
          "div",
          { class: "columns" },
          h("section", {}, h("h3", { text: "Evidence" }), h("ul", {}, explanation.evidence.map((item) => h("li", { text: item })))),
          h(
            "section",
            {},
            h("h3", { text: "Recommended actions" }),
            h("ol", {}, explanation.recommended_actions.map((item) => h("li", { text: item })))
          )
        ),
        h(
          "section",
          { class: "public-warning" },
          h("h3", { text: "Public warning draft" }),
          h("blockquote", { text: explanation.public_warning }),
          h(
            "div",
            { class: "public-warning-foot" },
            h("span", { class: "muted small", text: "Draft only — requires operator approval before release." }),
            copyButton
          )
        )
      ),
    ];
  }

  function renderExplanation() {
    const body = $("ibm-body");
    const button = $("explain-button");
    const loading = state.explainState === "loading";

    button.disabled = !state.event || loading || state.ibm.state === "missing";
    button.textContent = loading
      ? "Asking Granite…"
      : state.explanation && state.explanation.source === "granite"
        ? "Regenerate"
        : "Explain with Granite";

    const model = $("ibm-model");
    model.hidden = !state.ibm.modelId;
    model.textContent = state.ibm.modelId || "";

    if (loading) {
      body.replaceChildren(
        h(
          "div",
          { class: "loading", role: "status" },
          h("div", { class: "loading-line" }),
          h("div", { class: "loading-line" }),
          h("div", { class: "loading-line" }),
          h("p", { class: "muted small", text: `Sending ${state.event.event_id} to IBM watsonx.ai…` })
        )
      );
      return;
    }

    if (state.explainState === "error") {
      const hints = {
        not_configured: "Add WATSONX_API_KEY and WATSONX_PROJECT_ID to .env and restart the backend.",
        auth_failed: "Check the IBM Cloud API key and project access.",
        timeout: "IBM watsonx.ai did not respond in time.",
        unreachable: "The backend could not be reached.",
        invalid_output: "Granite responded, but not in the required JSON format. Retry usually fixes this.",
      };
      body.replaceChildren(
        h(
          "div",
          { class: "error-state", role: "alert" },
          h("p", {}, h("strong", { text: "Granite explanation unavailable. " }), state.explainError.message),
          hints[state.explainError.code] ? h("p", { class: "muted small", text: hints[state.explainError.code] }) : null,
          h("p", { class: "muted small", text: "Detection, the map, and alerts keep working without IBM." }),
          h(
            "div",
            { class: "error-actions" },
            h("button", { type: "button", class: "button small", text: "Retry", onclick: () => explain(true) }),
            h("button", { type: "button", class: "button small ghost", text: "Show prerecorded example", onclick: showPrerecorded })
          )
        )
      );
      return;
    }

    if (state.explainState === "done" && state.explanation) {
      body.replaceChildren(...explanationView(state.explanation));
      return;
    }

    let hint = "Run a scenario. Granite explains detector events; it never sets severity.";
    if (state.event) hint = `Ask Granite to explain ${state.event.event_id}.`;
    if (state.ibm.state === "not_configured") hint += " IBM credentials are not configured on the backend.";
    if (state.ibm.state === "missing") hint = "The backend does not expose the IBM explanation route yet.";
    body.replaceChildren(h("p", { class: "empty-state", text: hint }));
  }

  function render() {
    renderStatus();
    renderSummary();
    renderScenarios();
    renderNodes();
    renderChart();
    renderEvent();
    renderExplanation();
  }

  // ---------- Startup ----------

  async function connectBackend() {
    setBackend("checking");
    render();
    try {
      await api.health();
      setBackend("online");
      await Promise.all([refreshAll(), refreshIbmStatus()]);
    } catch (error) {
      handleBackendError(error);
    }
    render();
  }

  function startPolling() {
    setInterval(async () => {
      if (state.mode === "mock" || state.stream === "live" || state.runningScenario) return;
      try {
        await refreshAll({ live: true });
        if (state.ibm.state === "unknown") await refreshIbmStatus();
      } catch (error) {
        handleBackendError(error);
        return;
      }
      render();
    }, POLL_INTERVAL_MS);
  }

  function init() {
    mapView = window.WaveGuardMap.createMap($("map"), NODE_META);
    chartView = window.WaveGuardCharts.createChart($("level-chart"), NODE_META);
    $("api-url").textContent = API_BASE_URL;

    document.querySelectorAll("[data-scenario]").forEach((button) => {
      button.addEventListener("click", () => runScenario(button.dataset.scenario));
    });
    $("explain-button").addEventListener("click", () =>
      explain(Boolean(state.explanation && state.explanation.source === "granite"))
    );
    $("retry-backend").addEventListener("click", connectBackend);
    $("use-mock").addEventListener("click", () => {
      const url = new URL(window.location.href);
      url.searchParams.set("mock", "1");
      window.location.href = url.toString();
    });

    api.subscribe(handleLiveMessage, (status) => {
      state.stream = status;
      renderStatus();
    });
    connectBackend();
    startPolling();
  }

  window.WaveGuard = { API_BASE_URL, state };
  init();
})();
