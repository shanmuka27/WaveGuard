// WaveGuard demo control page: runs scenarios and sets which location the
// physical alert board shows. The dashboard (index.html) follows along live.
// Query parameter: ?api=http://host:8000 to point at another backend.
(function () {
  const params = new URLSearchParams(window.location.search);
  // The backend runs on the same machine that served this page (127.0.0.1 locally,
  // the laptop's network address when opened from a phone in phone mode).
  const defaultApi = window.location.protocol.startsWith("http")
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : "http://127.0.0.1:8000";
  const API_BASE_URL = (params.get("api") || defaultApi).replace(/\/+$/, "");

  const LOCATIONS = {
    "MANISTEE-06": "Manistee",
    "LUDINGTON-01": "Ludington",
    "MUSKEGON-02": "Muskegon",
    "GRANDHAVEN-04": "Grand Haven",
    "HOLLAND-03": "Holland",
    "SOUTHHAVEN-05": "South Haven",
  };
  const SCENARIO_NAMES = {
    normal: "Normal",
    local_disturbance: "Local disturbance",
    seiche: "Seiche",
    sudden_surge: "Sudden surge",
    manual: "Manual (live sensor)",
  };
  const BOARD_COLORS = {
    safe: "green",
    watch: "yellow",
    warning: "solid red",
    surge: "flashing red",
  };

  const $ = (id) => document.getElementById(id);
  const placeName = (nodeId) => (nodeId ? LOCATIONS[nodeId] || nodeId : "the whole shoreline");
  let running = false;

  async function request(path, method = "GET") {
    const response = await fetch(API_BASE_URL + path, { method, headers: { Accept: "application/json" } });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = body && body.detail;
      throw new Error(typeof detail === "string" ? detail : `HTTP ${response.status}`);
    }
    return body;
  }

  const query = (location) => (location ? `?location=${encodeURIComponent(location)}` : "");

  function setBackend(online) {
    const pill = $("status-backend");
    pill.dataset.tone = online ? "ok" : "bad";
    pill.querySelector(".value").textContent = online ? "Online" : "Offline";
  }

  // What the board shows for its location: the location's own severity, raised to
  // the latest event's when the event includes it (mirrors EventService.alert_for).
  async function describeBoard() {
    const [{ location }, situation] = await Promise.all([request("/api/board"), request("/api/agent/situation")]);
    const event = situation.latest_event;
    let severity;
    let surge = false;
    if (!location) {
      severity = situation.overall_severity;
      surge = Boolean(event && event.classification === "sudden_surge" && severity === "warning");
    } else {
      const node = situation.nodes.find((item) => item.node_id === location);
      severity = node ? node.severity : "safe";
      if (event && event.affected_nodes.includes(location)) {
        const rank = { safe: 0, watch: 1, warning: 2 };
        if (rank[event.severity] > rank[severity]) severity = event.severity;
        surge = event.classification === "sudden_surge" && severity === "warning";
      }
    }
    const color = BOARD_COLORS[surge ? "surge" : severity] || severity;
    $("board-status").textContent = `Alert board shows ${placeName(location)}: ${color}.`;
    $("board-status").dataset.severity = severity;
    return location;
  }

  async function setBoard(location) {
    try {
      await request(`/api/board${query(location)}`, "PUT");
      setBackend(true);
      await describeBoard();
    } catch (error) {
      setBackend(false);
      $("board-status").textContent = `Could not switch the board: ${error.message}`;
    }
  }

  function logRun(text) {
    const list = $("run-log");
    if (list.firstElementChild && list.firstElementChild.classList.contains("muted")) list.replaceChildren();
    const item = document.createElement("li");
    item.textContent = `${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}  ${text}`;
    list.prepend(item);
  }

  async function runScenario(scenario) {
    if (running) return;
    running = true;
    const location = $("scenario-location").value;
    const label = `${SCENARIO_NAMES[scenario]} at ${placeName(location)}`;
    document.querySelectorAll("[data-scenario]").forEach((button) => {
      button.disabled = true;
      button.setAttribute("aria-busy", String(button.dataset.scenario === scenario));
    });
    $("scenario-status").textContent = `Running ${label}…`;
    try {
      const result = await request(`/api/scenarios/${scenario}${query(location)}`, "POST");
      setBackend(true);
      const event = result.event;
      const outcome = event
        ? `${event.classification.replace(/_/g, " ")} · ${event.severity} at ${event.affected_nodes.map((id) => placeName(id)).join(", ")}`
        : "no hazard event";
      $("scenario-status").textContent = scenario === "manual"
        ? "Manual: Ludington now shows the live tray sensor."
        : `${label}: ${outcome}. Plays until you pick another.`;
      logRun(`${label} → ${outcome}`);
      if (result.source_note) logRun(`   data: ${result.source_note}`);
      await describeBoard();
      await refreshSensor();
    } catch (error) {
      setBackend(false);
      $("scenario-status").textContent = `${label} failed: ${error.message}`;
    } finally {
      running = false;
      document.querySelectorAll("[data-scenario]").forEach((button) => {
        button.disabled = false;
        button.setAttribute("aria-busy", "false");
      });
    }
  }

  // Live sensor panel: what the tray sensor reads, and whether it is driving Ludington.
  async function refreshSensor() {
    const sensor = await request("/api/sensor");
    const chip = $("mode-chip");
    chip.textContent = sensor.manual ? "Manual · live" : "Scenario playing";
    $("calibrate-button").disabled = !sensor.manual;
    $("neighbor-button").disabled = !sensor.manual;
    const latest = sensor.latest;
    const zero = `zero at ${sensor.reference_distance_cm} cm`;
    if (!sensor.manual) {
      $("sensor-reading").textContent = `Sensor paused while a scenario plays · press Manual (5) to use it · ${zero}`;
      $("sensor-reading").dataset.severity = "";
    } else if (!latest) {
      $("sensor-reading").textContent = `No sensor readings yet. Check the Arduino is plugged in · ${zero}`;
      $("sensor-reading").dataset.severity = "watch";
    } else {
      const good = latest.quality >= 0.95;
      $("sensor-reading").textContent = good
        ? `Level ${latest.level_cm.toFixed(2)} cm · ${latest.distance_cm.toFixed(1)} cm from sensor · ${zero}`
        : `No echo (quality ${latest.quality}) · point the sensor straight down at the water · ${zero}`;
      $("sensor-reading").dataset.severity = good ? "safe" : "watch";
    }
  }

  // Raw sensor view: the dashboard plots only the tray sensor's own readings.
  function showRawView(on) {
    const button = $("raw-view-button");
    button.setAttribute("aria-pressed", String(on));
    button.textContent = `Raw sensor view: ${on ? "on" : "off"}`;
    button.classList.toggle("primary", on);
  }

  async function toggleRawView() {
    const on = $("raw-view-button").getAttribute("aria-pressed") !== "true";
    try {
      // Raw sensor data only exists in Manual mode; switch there first.
      const sensor = await request("/api/sensor");
      if (on && !sensor.manual) await runScenario("manual");
      const view = await request(`/api/view?sensor_only=${on}`, "PUT");
      showRawView(view.sensor_only);
      logRun(view.sensor_only ? "Dashboard: raw sensor view" : "Dashboard: normal view");
    } catch (error) {
      $("calibrate-status").textContent = `Could not switch the view: ${error.message}`;
    }
  }

  async function calibrate() {
    $("calibrate-button").disabled = true;
    $("calibrate-status").textContent = "Calibrating… keep the water still.";
    try {
      const result = await request("/api/sensor/calibrate", "POST");
      $("calibrate-status").textContent =
        `Zero set at ${result.reference_distance_cm} cm (${result.samples} readings, spread ${result.spread_cm} cm). Saved.`;
      logRun(`Calibrated zero at ${result.reference_distance_cm} cm`);
    } catch (error) {
      $("calibrate-status").textContent = error.message;
    }
    await refreshSensor().catch(() => {});
  }

  async function triggerNeighbors() {
    const button = $("neighbor-button");
    button.disabled = true;
    $("scenario-status").textContent = "Saving simulated neighbor response…";
    try {
      const result = await request("/api/sensor/neighbor-response", "POST");
      const outcome = result.event
        ? `${result.event.severity.toUpperCase()} · ${result.event.affected_nodes.join(", ")}`
        : "No shared pattern yet";
      $("scenario-status").textContent = `Neighbor response: ${outcome}. Open the dashboard and click Replay event.`;
      logRun(`Simulated neighbors derived from live Ludington → ${outcome}`);
      await describeBoard();
    } catch (error) {
      $("scenario-status").textContent = `Neighbor response unavailable: ${error.message}`;
    } finally {
      button.disabled = false;
    }
  }

  async function init() {
    $("calibrate-button").addEventListener("click", calibrate);
    $("raw-view-button").addEventListener("click", toggleRawView);
    request("/api/view").then((view) => showRawView(view.sensor_only)).catch(() => {});
    $("neighbor-button").addEventListener("click", triggerNeighbors);
    document.querySelectorAll("[data-scenario]").forEach((button) => {
      button.addEventListener("click", () => runScenario(button.dataset.scenario));
    });
    $("scenario-location").addEventListener("change", (event) => setBoard(event.target.value || null));
    document.addEventListener("keydown", (event) => {
      if (event.target instanceof HTMLSelectElement || event.altKey || event.ctrlKey || event.metaKey) return;
      const button = document.querySelector(`[data-key="${event.key}"]`);
      if (button) {
        event.preventDefault();
        runScenario(button.dataset.scenario);
      }
    });

    // Start from wherever the board currently is, rather than overriding it.
    try {
      const location = await describeBoard();
      $("scenario-location").value = location || "";
      setBackend(true);
    } catch (error) {
      setBackend(false);
      $("board-status").textContent = `Backend unreachable at ${API_BASE_URL}.`;
    }
    refreshSensor().catch(() => {});
    setInterval(() => describeBoard().catch(() => setBackend(false)), 3000);
    setInterval(() => refreshSensor().catch(() => {}), 2000);
  }

  init();
})();
