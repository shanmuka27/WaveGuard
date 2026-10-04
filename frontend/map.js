// Shoreline node map. Uses Leaflet when available and falls back to a text notice.
(function () {
  const SEVERITY_COLORS = {
    safe: "#2fbf71",
    watch: "#f2b134",
    warning: "#ef4b4b",
    unknown: "#5d7b8a",
  };

  function createMap(element, nodeMeta) {
    if (!window.L) {
      element.innerHTML =
        '<p class="map-fallback">Map library unavailable. Node states are listed below.</p>';
      return { update() {} };
    }

    const map = L.map(element, {
      zoomControl: false,
      attributionControl: true,
      scrollWheelZoom: false,
    });
    L.control.zoom({ position: "topright" }).addTo(map);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 12,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
    }).addTo(map);

    const coordinates = Object.values(nodeMeta).map((meta) => [meta.lat, meta.lng]);
    // Keep every node in view whenever the map's box changes size (layout
    // switches, window resizes, the grid settling after load).
    const refit = () => {
      map.invalidateSize();
      map.fitBounds(coordinates, { padding: [36, 36] });
    };
    refit();

    const markers = new Map();
    const halos = new Map();

    function update(nodes) {
      for (const node of nodes) {
        const meta = nodeMeta[node.node_id];
        if (!meta) continue;

        const color = SEVERITY_COLORS[node.severity] || SEVERITY_COLORS.unknown;
        // The physical station keeps its solid marker while playing scenario data.
        const playingScenario = Boolean(meta.physicalStation) && node.source === "simulated";
        const simulated = node.source !== "physical" && !playingScenario;
        const style = {
          radius: 10,
          color: "#eef8fb",
          weight: 2,
          dashArray: simulated ? "4 3" : null,
          fillColor: color,
          fillOpacity: simulated ? 0.75 : 1,
        };
        const sourceLabel = playingScenario ? "SCENARIO" : node.source ? node.source.toUpperCase() : "NO DATA";
        // Nearby towns alternate sides (meta.labelSide) so their labels do not stack.
        const label = `${meta.location} · ${sourceLabel}`;

        let marker = markers.get(node.node_id);
        if (!marker) {
          marker = L.circleMarker([meta.lat, meta.lng], style)
            .bindTooltip(label, {
              permanent: true,
              direction: meta.labelSide || "right",
              offset: [meta.labelSide === "left" ? -12 : 12, 0],
              className: "node-label",
            })
            .addTo(map);
          markers.set(node.node_id, marker);
        } else {
          marker.setStyle(style);
          marker.setTooltipContent(label);
        }

        let halo = halos.get(node.node_id);
        if (node.severity === "warning") {
          if (!halo) {
            halo = L.circle([meta.lat, meta.lng], {
              radius: 14000,
              color,
              weight: 1,
              fillColor: color,
              fillOpacity: 0.15,
              interactive: false,
            }).addTo(map);
            halos.set(node.node_id, halo);
          }
        } else if (halo) {
          halo.remove();
          halos.delete(node.node_id);
        }
      }
    }

    setTimeout(refit, 0);
    if (window.ResizeObserver) new ResizeObserver(refit).observe(element);
    else window.addEventListener("resize", refit);

    return { update };
  }

  window.WaveGuardMap = { createMap, SEVERITY_COLORS };
})();
