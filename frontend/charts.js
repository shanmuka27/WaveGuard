// Live multi-series water-level chart. Simulated nodes are drawn with dashed lines.
(function () {
  const FALLBACK_COLORS = ["#4fd1e8", "#b69cff", "#ff8fb8", "#9ad97b", "#f5c46b"];

  function formatTime(ms) {
    return new Date(ms).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  function createChart(canvas, nodeMeta) {
    if (!window.Chart) {
      canvas.replaceWith(
        Object.assign(document.createElement("p"), {
          className: "map-fallback",
          textContent: "Chart library unavailable.",
        })
      );
      return { setSeries() {} };
    }

    Chart.defaults.color = "#8fb0c0";
    Chart.defaults.borderColor = "#1c4257";
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;

    const chart = new Chart(canvas, {
      type: "line",
      data: { datasets: [] },
      options: {
        animation: false,
        maintainAspectRatio: false,
        parsing: false,
        normalized: true,
        interaction: { mode: "nearest", axis: "x", intersect: false },
        scales: {
          x: {
            type: "linear",
            ticks: { callback: (value) => formatTime(value), maxRotation: 0, autoSkipPadding: 24 },
            grid: { color: "#173a4d" },
          },
          y: {
            title: { display: true, text: "cm" },
            grid: { color: "#173a4d" },
          },
        },
        plugins: {
          legend: {
            position: "bottom",
            labels: { usePointStyle: true, pointStyle: "line", boxWidth: 28 },
          },
          tooltip: {
            callbacks: {
              title: (items) => (items.length ? formatTime(items[0].parsed.x) : ""),
              label: (item) => ` ${item.dataset.label}: ${item.parsed.y.toFixed(2)} cm`,
            },
          },
        },
      },
    });

    // raw: straight segments with a dot per reading; minSpan: smallest y range
    // shown, so sensor jitter is not magnified into fake waves.
    function setSeries(series, { yTitle = "cm", raw = false, minSpan = null } = {}) {
      chart.options.scales.y.title.text = yTitle;
      const values = [...series.values()].flatMap((entry) => entry.points.map((p) => p.y)).filter((y) => y !== null);
      if (minSpan && values.length) {
        const mid = (Math.min(...values) + Math.max(...values)) / 2;
        const half = Math.max(minSpan, Math.max(...values) - Math.min(...values) + 0.5) / 2;
        chart.options.scales.y.min = Math.floor((mid - half) * 2) / 2;
        chart.options.scales.y.max = Math.ceil((mid + half) * 2) / 2;
      } else {
        delete chart.options.scales.y.min;
        delete chart.options.scales.y.max;
      }
      const datasets = [];
      let index = 0;
      for (const [nodeId, entry] of series) {
        const color = nodeMeta[nodeId]?.color || FALLBACK_COLORS[index % FALLBACK_COLORS.length];
        // The physical station keeps a solid line even while it plays scenario
        // data; the legend still says which data it is showing.
        const station = Boolean(nodeMeta[nodeId]?.physicalStation);
        const live = entry.source === "physical";
        const simulated = !live && !station;
        const kind = live ? "live sensor" : station ? "simulated scenario" : entry.source || "unknown";
        datasets.push({
          label: entry.label || `${nodeId} (${kind})`,
          data: entry.points,
          borderColor: color,
          backgroundColor: color,
          borderWidth: simulated ? 2 : 3,
          borderDash: simulated ? [6, 4] : [],
          pointRadius: raw ? 2.5 : 0,
          pointHitRadius: 6,
          tension: raw ? 0 : 0.3,
        });
        index += 1;
      }
      chart.data.datasets = datasets;
      chart.update("none");
    }

    return { setSeries, resize: () => chart.resize() };
  }

  window.WaveGuardCharts = { createChart };
})();
