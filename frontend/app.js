// WaveGuard operator dashboard.
// Query parameters: ?api=http://host:8000 to point at another backend, ?mock=1 to use mock
// data, and ?mock=1&physical=1 to add a fake 1 Hz Arduino stream for LUDINGTON-01.
(function () {
  const params = new URLSearchParams(window.location.search);
  // The backend runs on the same machine that served this page (127.0.0.1 locally,
  // the laptop's network address when opened from a phone in phone mode).
  const defaultApi = window.location.protocol.startsWith("http")
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : "http://127.0.0.1:8000";
  const API_BASE_URL = (params.get("api") || defaultApi).replace(/\/+$/, "");
  const WS_URL = `${API_BASE_URL.replace(/^http/, "ws")}/ws/live`;

  const SCENARIO_READING_COUNT = 72; // 12 steps x 6 nodes, see backend/routes/scenarios.py
  const MAX_POINTS_PER_NODE = 120;
  const CHART_WINDOW_MS = 2 * 60 * 1000;
  const HISTORY_FETCH_LIMIT = 60;
  const HISTORY_ROWS = 12;
  const HISTORY_REFRESH_DEBOUNCE_MS = 800;
  // The firmware reports quality 0.10 for a missed echo and 0.50 for an out-of-range target.
  const MIN_PLOTTED_QUALITY = 0.5;
  const isUsableReading = (reading) => reading.quality > MIN_PLOTTED_QUALITY;
  const POLL_INTERVAL_MS = 3000;
  const NODES_REFRESH_DEBOUNCE_MS = 400;
  const CLOCK_SKEW_TOLERANCE_MS = 30000;

  const SEVERITY_RANK = { unknown: -1, safe: 0, watch: 1, warning: 2 };
  const CLASSIFICATION_LABELS = {
    normal: "Normal",
    local_disturbance: "Local disturbance",
    seiche_like: "Seiche-like oscillation",
    sudden_surge: "Sudden surge",
    sensor_fault: "Sensor fault",
  };
  const NODE_META = {
    "LUDINGTON-01": { location: "Ludington", labelSide: "right", physicalStation: true, lat: 43.9553, lng: -86.4526, color: "#4fd1e8" },
    "MUSKEGON-02": { location: "Muskegon", labelSide: "left", lat: 43.2342, lng: -86.2484, color: "#b69cff" },
    "HOLLAND-03": { location: "Holland", labelSide: "left", lat: 42.7725, lng: -86.2119, color: "#ff8fb8" },
    "GRANDHAVEN-04": { location: "Grand Haven", labelSide: "right", lat: 43.0567, lng: -86.2486, color: "#7aa7ff" },
    "SOUTHHAVEN-05": { location: "South Haven", labelSide: "right", lat: 42.4031, lng: -86.2861, color: "#9fe3c4" },
    "MANISTEE-06": { location: "Manistee", labelSide: "left", lat: 44.2483, lng: -86.3439, color: "#f4b6a0" },
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
    history: [], // newest first, from GET /api/events
    sourceNote: null, // what the running scenario replays (NOAA records, synthetic parts)
    clockOffsets: new Map(), // node_id -> ms added to unsynced physical timestamps
    explainToken: 0,
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

  function sourceTag(source, nodeId) {
    if (source === "physical") return h("span", { class: "tag physical", text: "Physical" });
    // The physical station playing a demo scenario: generated data, solid styling.
    if (source === "simulated" && (NODE_META[nodeId] || {}).physicalStation) {
      return h("span", { class: "tag physical", text: "Scenario" });
    }
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

    events(limit) {
      return this.request(`/api/events?limit=${limit}`);
    }

    currentScenario() {
      return this.request("/api/scenarios/current");
    }

    async latestEvent() {
      try {
        return await this.request("/api/events/latest");
      } catch (error) {
        if (error.status === 404) return null;
        throw error;
      }
    }

    // Which location the physical alert board shows; "" = whole network.
    setBoardLocation(location) {
      const query = location ? `?location=${encodeURIComponent(location)}` : "";
      return this.request(`/api/board${query}`, { method: "PUT" });
    }

    runScenario(scenario, location) {
      const query = location ? `?location=${encodeURIComponent(location)}` : "";
      return this.request(`/api/scenarios/${encodeURIComponent(scenario)}${query}`, {
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

    example() {
      return this.request("/api/ibm/example");
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

  // Live demos are driven from admin.html; the dashboard shows its own scenario
  // controls only in mock mode, where there is no backend for admin.html to drive.
  const DEMO_CONTROLS = state.mode === "mock";

  const api = state.mode === "mock" ? new window.WaveGuardMock.MockApi({ physical: params.get("physical") === "1" }) : new HttpApi(API_BASE_URL);

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

  // The Arduino stamps readings from its own clock, which is not synced to the
  // backend. Plot unsynced live physical readings at receive time instead.
  function trackClockSkew(reading) {
    const skew = Date.now() - Date.parse(reading.timestamp);
    if (reading.source === "physical" && Math.abs(skew) > CLOCK_SKEW_TOLERANCE_MS) {
      state.clockOffsets.set(reading.node_id, skew);
    } else {
      state.clockOffsets.delete(reading.node_id);
    }
  }

  function addReading(reading) {
    if (reading.source !== "physical") state.clockOffsets.delete(reading.node_id);
    let entry = state.series.get(reading.node_id);
    if (!entry || entry.source !== reading.source) {
      // Matches the backend: a source switch starts a fresh signal window.
      entry = { source: reading.source, points: [] };
      state.series.set(reading.node_id, entry);
    }
    const offset = reading.source === "physical" ? state.clockOffsets.get(reading.node_id) || 0 : 0;
    // A failed echo is not a water level: draw it as a gap so it neither spikes
    // the line nor stretches the y-axis.
    entry.points.push({
      x: Date.parse(reading.timestamp) + offset,
      y: isUsableReading(reading) ? reading.water_level_cm : null,
    });
    entry.points.sort((a, b) => a.x - b.x);
    if (entry.points.length > MAX_POINTS_PER_NODE) {
      entry.points.splice(0, entry.points.length - MAX_POINTS_PER_NODE);
    }

    const node = state.nodes.get(reading.node_id);
    if (node) node.last_reading = reading;
    else state.nodes.set(reading.node_id, { node_id: reading.node_id, source: reading.source, severity: "safe", last_reading: reading });
  }

  function replaceSeries(readings) {
    state.series.clear();
    readings
      .slice()
      .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp))
      .forEach(addReading);
  }

  async function reloadReadings(limit = SCENARIO_READING_COUNT) {
    replaceSeries(await api.latestReadings(limit));
  }

  async function refreshNodes() {
    const nodes = await api.nodes();
    state.nodes = new Map(nodes.map((node) => [node.node_id, node]));
  }

  async function refreshHistory() {
    state.history = await api.events(HISTORY_FETCH_LIMIT);
  }

  let historyRefreshTimer = null;
  function scheduleHistoryRefresh() {
    clearTimeout(historyRefreshTimer);
    historyRefreshTimer = setTimeout(async () => {
      try {
        await refreshHistory();
        scheduleRender();
      } catch (error) {
        handleBackendError(error);
      }
    }, HISTORY_REFRESH_DEBOUNCE_MS);
  }

  // Review a past event: it replaces the evidence panel and clears any explanation
  // of a different event, so "Explain with Granite" then explains this one.
  function selectHistoryEvent(event) {
    setEvent(event, { newRun: true });
    render();
  }

  let nodesRefreshTimer = null;
  function scheduleNodesRefresh() {
    clearTimeout(nodesRefreshTimer);
    nodesRefreshTimer = setTimeout(async () => {
      try {
        await refreshNodes();
        scheduleRender();
      } catch (error) {
        handleBackendError(error);
      }
    }, NODES_REFRESH_DEBOUNCE_MS);
  }

  function resetExplanation() {
    state.explainToken += 1;
    state.explanation = null;
    state.explainState = "idle";
    state.explainError = null;
  }

  // newRun: the event comes from a fresh scenario run, so any earlier explanation
  // no longer applies. Otherwise (live sensor updates) the last explanation stays
  // visible and is marked as covering an earlier event.
  function setEvent(event, { fromLive = false, newRun = false } = {}) {
    const previous = state.event;
    if (previous && event && previous.event_id === event.event_id) return;

    state.event = event || null;
    if (eventSignature(previous) !== eventSignature(state.event) && (newRun || !event)) {
      resetExplanation();
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
    const [nodes, readings, event, history, scenario] = await Promise.all([
      api.nodes(),
      api.latestReadings(SCENARIO_READING_COUNT),
      api.latestEvent(),
      api.events(HISTORY_FETCH_LIMIT),
      api.currentScenario().catch(() => null),
    ]);
    state.sourceNote = scenario ? scenario.source_note : state.sourceNote;
    state.nodes = new Map(nodes.map((node) => [node.node_id, node]));
    state.history = history;
    replaceSeries(readings);
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
        if (message.reading) {
          trackClockSkew(message.reading);
          addReading(message.reading);
        }
        if (message.event) {
          setEvent(message.event, { fromLive: true });
          scheduleHistoryRefresh();
        }
        scheduleNodesRefresh();
        break;
      case "scenario_complete":
        state.sourceNote = message.source_note || null;
        setEvent(message.event, { fromLive: true, newRun: true });
        Promise.all([reloadReadings(), refreshNodes(), refreshHistory()])
          .then(scheduleRender)
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
    scheduleRender();
  }

  // Coalesce bursts of live messages (1 Hz sensor plus node refreshes) into one render per frame.
  let renderQueued = false;
  function scheduleRender() {
    if (renderQueued) return;
    renderQueued = true;
    const flush = () => {
      renderQueued = false;
      render();
    };
    if (window.requestAnimationFrame) window.requestAnimationFrame(flush);
    else setTimeout(flush, 16);
  }

  // ---------- Actions ----------

  // The scenario's center: a node id, or "" for the whole shoreline.
  function scenarioLocation() {
    return $("scenario-location").value;
  }

  function locationName(nodeId) {
    return nodeId ? (NODE_META[nodeId] || {}).location || nodeId : "the whole shoreline";
  }

  function selectLocation(nodeId) {
    $("scenario-location").value = nodeId;
    renderNodes();
    syncBoardLocation();
  }

  // The physical board stands in for the selected location's own alert board.
  async function syncBoardLocation() {
    const location = scenarioLocation();
    try {
      await api.setBoardLocation(location || null);
      $("scenario-status").textContent = `Board now shows ${locationName(location)}.`;
    } catch (error) {
      $("scenario-status").textContent = `Could not switch the board: ${error.message}`;
      handleBackendError(error);
    }
  }

  async function runScenario(scenario) {
    if (state.runningScenario) return;
    state.runningScenario = scenario;
    const location = scenarioLocation();
    const label = `${scenario.replace(/_/g, " ")} at ${locationName(location)}`;
    $("scenario-status").textContent = `Running ${label}…`;
    resetExplanation();
    render();
    try {
      const result = await api.runScenario(scenario, location || null);
      setEvent(result.event, { fromLive: true, newRun: true });
      await Promise.all([reloadReadings(result.readings_generated || SCENARIO_READING_COUNT), refreshNodes()]);
      state.lastScenario = scenario;
      setBackend("online");
      touch();
      const outcome = result.event
        ? `${CLASSIFICATION_LABELS[result.event.classification] || result.event.classification} · ${result.event.severity}`
        : "no hazard event";
      $("scenario-status").textContent = `${label} complete: ${outcome}.`;
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
    // A new scenario run bumps the token; results for an older run are dropped.
    // Results for an event the sensor stream has since superseded are kept and marked.
    const token = ++state.explainToken;
    state.explainState = "loading";
    state.explainError = null;
    render();
    try {
      const result = await api.explain(event.event_id, refresh);
      if (token !== state.explainToken) return;
      state.explanation = result;
      state.explainState = "done";
      if (state.mode !== "mock") state.ibm = { ...state.ibm, state: "ready", message: null };
    } catch (error) {
      if (token !== state.explainToken) return;
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
      state.explanation = await api.example();
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

    // The affected towns, by name, so the severity box reads at a glance.
    const affected = isEventActive() ? state.event.affected_nodes : [];
    $("summary-places").replaceChildren(
      ...affected.map((nodeId) =>
        h(
          "li",
          { class: `place ${effectiveSeverity(nodeId)}` },
          h("span", { class: "place-name", text: (NODE_META[nodeId] || {}).location || nodeId }),
          h("span", { class: "place-id", text: nodeId })
        )
      )
    );

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
        usable: Boolean(node && node.last_reading && isUsableReading(node.last_reading)),
      };
    });
    mapView.update(rows);

    $("node-list").replaceChildren(
      ...rows.map((row) =>
        h(
          "li",
          DEMO_CONTROLS
            ? {
                class: `node-row selectable${row.node_id === scenarioLocation() ? " chosen" : ""}`,
                title: `Center demo scenarios on ${locationName(row.node_id)}`,
                onclick: () => selectLocation(row.node_id),
              }
            : { class: "node-row" },
          h("span", { class: "swatch", style: `background:${(NODE_META[row.node_id] || {}).color || "#5d7b8a"}` }),
          h(
            "span",
            {},
            h("span", { class: "node-name", text: row.node_id }),
            " ",
            h("span", { class: "muted small", text: (NODE_META[row.node_id] || {}).location || "" })
          ),
          sourceTag(row.source, row.node_id),
          h(
            "span",
            { class: "node-level" },
            row.level == null ? "—" : row.usable ? `${row.level.toFixed(2)} cm` : "No echo",
            " ",
            severityBadge(row.severity)
          )
        )
      )
    );
  }

  function renderChart() {
    // Show a rolling window ending at the newest reading, so stale lines from an
    // earlier scenario can't stretch the time axis and squash the live sensor.
    // During an active event, show only the locations it affects.
    const focus = isEventActive() ? new Set(state.event.affected_nodes) : null;
    const newest = Math.max(
      ...[...state.series.values()].map((entry) => entry.points.at(-1)?.x ?? -Infinity)
    );
    const series = new Map(
      orderedNodeIds()
        .filter((nodeId) => state.series.has(nodeId) && (!focus || focus.has(nodeId)))
        .map((nodeId) => {
          const entry = state.series.get(nodeId);
          const points = entry.points.filter((point) => point.x >= newest - CHART_WINDOW_MS);
          return [nodeId, { ...entry, points }];
        })
        .filter(([, entry]) => entry.points.length > 0)
    );
    chartView.setSeries(series);
    $("chart-empty").hidden = series.size > 0;

    const unsynced = [...state.clockOffsets.keys()].filter(
      (nodeId) => state.series.get(nodeId)?.source === "physical"
    );
    const notes = [
      focus
        ? `Showing the ${focus.size} location${focus.size === 1 ? "" : "s"} in the current event`
        : "Solid: Ludington station · dashed: simulated nodes",
    ];
    if (unsynced.length) notes.push(`${unsynced.join(", ")} clock not synced, plotted at receive time`);
    if (state.sourceNote) notes.push(state.sourceNote);
    for (const [nodeId, entry] of series) {
      const recent = entry.points.slice(-30);
      const missed = recent.filter((point) => point.y === null).length;
      if (missed) notes.push(`${nodeId}: ${missed} of last ${recent.length} readings had no echo (gaps)`);
    }
    $("chart-note").textContent = notes.join(" · ");
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

  // Consecutive detections of the same situation (same kind, nodes and severity)
  // collapse into one row, so a sensor re-reporting every few seconds stays readable.
  function groupedHistory() {
    const groups = [];
    for (const event of state.history) {
      const last = groups.at(-1);
      if (last && eventSignature(last.event) === eventSignature(event)) {
        last.count += 1;
        last.firstAt = event.detected_at;
      } else {
        groups.push({ event, count: 1, firstAt: event.detected_at });
      }
    }
    return groups.slice(0, HISTORY_ROWS);
  }

  function renderHistory() {
    const body = $("history-body");
    const groups = groupedHistory();
    if (!groups.length) {
      body.replaceChildren(h("p", { class: "empty-state", text: "No events detected yet. Run a scenario to create one." }));
      return;
    }

    const selectedId = state.event && state.event.event_id;
    const rows = groups.map(({ event, count, firstAt }) => {
      const select = () => selectHistoryEvent(event);
      const time = count > 1 ? `${formatTime(firstAt)}–${formatTime(event.detected_at)}` : formatTime(event.detected_at);
      return h(
        "tr",
        {
          class: event.event_id === selectedId ? "selected" : null,
          tabindex: "0",
          onclick: select,
          onkeydown: (keyEvent) => {
            if (keyEvent.key === "Enter" || keyEvent.key === " ") {
              keyEvent.preventDefault();
              select();
            }
          },
        },
        h("td", {}, time),
        h(
          "td",
          {},
          CLASSIFICATION_LABELS[event.classification] || event.classification,
          count > 1 ? h("span", { class: "repeat", text: `×${count}` }) : null
        ),
        h("td", {}, severityBadge(event.severity)),
        h("td", { title: event.affected_nodes.join(", ") }, String(event.affected_nodes.length)),
        h("td", {}, `${event.amplitude_cm.toFixed(1)} cm`)
      );
    });

    body.replaceChildren(
      h(
        "div",
        { class: "history-scroll" },
        h(
          "table",
          { class: "history-table" },
          h(
            "thead",
            {},
            h("tr", {}, h("th", { text: "Time" }), h("th", { text: "Event" }), h("th", { text: "Severity" }), h("th", { text: "Nodes" }), h("th", { text: "Amplitude" }))
          ),
          h("tbody", {}, rows)
        )
      )
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
          return h("li", {}, nodeId, sourceTag(node ? node.source : null, nodeId));
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

    const warningIcon = () => {
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 24 24");
      svg.setAttribute("class", "warning-icon");
      svg.setAttribute("aria-hidden", "true");
      svg.innerHTML = '<path d="M12 3 2 20h20L12 3z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M12 10v4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="17" r="1.2" fill="currentColor"/>';
      return svg;
    };

    return [
      h(
        "p",
        { class: "source-label" },
        sourceTagView,
        result.model_id ? h("span", { class: "chip", text: result.model_id }) : null,
        result.simulated ? h("span", { class: "chip", text: "Simulated data" }) : null,
        h("span", { text: `${result.event_id} · ${formatTime(result.generated_at)}` }),
        note ? h("span", { text: note }) : null
      ),
      h(
        "div",
        { class: "explanation" },
        h(
          "section",
          { class: "explain-lead" },
          h("h3", { text: "Operator summary" }),
          h("p", { text: explanation.summary })
        ),
        h(
          "div",
          { class: "explain-cards" },
          h(
            "section",
            { class: "explain-card" },
            h("h3", { text: `Evidence (${explanation.evidence.length})` }),
            h("ul", { class: "evidence-list" }, explanation.evidence.map((item) => h("li", { text: item })))
          ),
          h(
            "section",
            { class: "explain-card" },
            h("h3", { text: `Recommended actions (${explanation.recommended_actions.length})` }),
            h("ol", { class: "action-list" }, explanation.recommended_actions.map((item) => h("li", { text: item })))
          )
        ),
        h(
          "section",
          { class: "public-warning" },
          h(
            "div",
            { class: "public-warning-head" },
            warningIcon(),
            h("h3", { text: "Public warning draft" }),
            h("span", { class: "badge watch", text: "Needs approval" })
          ),
          h("blockquote", { text: explanation.public_warning }),
          h(
            "div",
            { class: "public-warning-foot" },
            h("span", { class: "muted small", text: "Review before release. Granite drafts; an operator decides." }),
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
    const explainsCurrent = Boolean(
      state.explanation && state.event && state.explanation.event_id === state.event.event_id
    );
    button.textContent = loading
      ? state.mode === "mock" ? "Generating mock explanation…" : "Asking Granite…"
      : state.explanation && !explainsCurrent
        ? state.mode === "mock" ? "Explain latest mock event" : "Explain latest event"
        : state.explanation && state.explanation.source === "granite"
          ? "Regenerate"
          : state.mode === "mock" ? "Generate mock explanation" : "Explain with Granite";

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
          h("p", {
            class: "muted small",
            text: state.mode === "mock"
              ? `Generating a local explanation for ${state.event.event_id}…`
              : `Sending ${state.event.event_id} to IBM watsonx.ai…`,
          })
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
      const staleNote =
        !explainsCurrent && state.event
          ? h("p", {
              class: "stale-note",
              role: "note",
              text: state.explanation.source === "prerecorded"
                ? `Saved example ${state.explanation.event_id} does not describe the current event ${state.event.event_id}.`
                : `Explains earlier event ${state.explanation.event_id}. The detector now reports ${
                    CLASSIFICATION_LABELS[state.event.classification] || state.event.classification
                  } · ${state.event.severity} (${state.event.event_id}).`,
            })
          : null;
      body.replaceChildren(...[staleNote, ...explanationView(state.explanation)].filter(Boolean));
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
    renderHistory();
  }

  // ---------- Startup ----------

  async function connectBackend() {
    setBackend("checking");
    render();
    try {
      await api.health();
      setBackend("online");
      await Promise.all([refreshAll(), refreshIbmStatus()]);
      // Opened mid-demo: explain the active warning right away (cached per event on the backend).
      if (state.event && isEventActive() && state.event.severity === "warning" && $("auto-explain").checked) {
        explain();
      }
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
    $("demo-panel").hidden = !DEMO_CONTROLS;

    document.querySelectorAll("[data-scenario]").forEach((button) => {
      button.addEventListener("click", () => runScenario(button.dataset.scenario));
    });
    $("scenario-location").addEventListener("change", () => {
      renderNodes();
      syncBoardLocation();
    });
    $("explain-button").addEventListener("click", () => {
      const current = state.explanation;
      explain(Boolean(current && current.source === "granite" && state.event && current.event_id === state.event.event_id));
    });
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

  window.WaveGuard = { API_BASE_URL, state, api };
  init();
})();
