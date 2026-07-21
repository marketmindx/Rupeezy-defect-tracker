/**
 * Dashboard charts (Chart.js, vendored locally).
 *
 * Reads the JSON payload embedded in #dashboard-data, renders every chart,
 * and rebuilds them whenever data-bs-theme flips so axis/legend colors
 * follow light/dark mode.
 */
(() => {
  "use strict";

  const dataEl = document.getElementById("dashboard-data");
  if (!dataEl || typeof Chart === "undefined") return;
  const data = JSON.parse(dataEl.textContent);

  const SEVERITIES = ["Critical", "High", "Medium", "Low"];
  const SEVERITY_COLORS = { Critical: "#dc3545", High: "#fd7e14", Medium: "#ffc107", Low: "#20c997" };
  const PRIORITY_COLORS = { P0: "#dc3545", P1: "#fd7e14", P2: "#0d6efd", P3: "#6c757d" };
  const AGING_COLORS = ["#20c997", "#ffc107", "#fd7e14", "#dc3545", "#842029"];

  const charts = [];

  const css = (name, fallback) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

  const applyThemeDefaults = () => {
    Chart.defaults.color = css("--bs-secondary-color", "#6c757d");
    Chart.defaults.borderColor = css("--bs-border-color", "#dee2e6");
  };

  const make = (id, config) => {
    const el = document.getElementById(id);
    if (el) charts.push(new Chart(el, config));
  };

  const doughnutOpts = {
    maintainAspectRatio: false,
    cutout: "62%",
    plugins: { legend: { position: "bottom" } },
  };

  const barOpts = (horizontal, stacked) => ({
    maintainAspectRatio: false,
    indexAxis: horizontal ? "y" : "x",
    scales: {
      x: { stacked: !!stacked, beginAtZero: true, ticks: { precision: 0 } },
      y: { stacked: !!stacked, beginAtZero: true, ticks: { precision: 0 } },
    },
    plugins: { legend: stacked ? { position: "bottom" } : { display: false } },
  });

  const build = () => {
    charts.forEach((chart) => chart.destroy());
    charts.length = 0;
    applyThemeDefaults();

    make("chart-trend", {
      type: "line",
      data: {
        labels: data.trend.labels,
        datasets: [
          { label: "Reported", data: data.trend.created, borderColor: "#0d6efd",
            backgroundColor: "rgba(13,110,253,.12)", fill: true, tension: 0.3, pointRadius: 2 },
          { label: "Resolved", data: data.trend.resolved, borderColor: "#198754",
            backgroundColor: "rgba(25,135,84,.12)", fill: true, tension: 0.3, pointRadius: 2 },
        ],
      },
      options: {
        maintainAspectRatio: false,
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
        plugins: { legend: { position: "bottom" } },
      },
    });

    make("chart-open-closed", {
      type: "doughnut",
      data: {
        labels: ["Open", "Completed"],
        datasets: [{
          data: [data.open_vs_closed.open, data.open_vs_closed.done],
          backgroundColor: ["#0d6efd", "#198754"],
          borderWidth: 0,
        }],
      },
      options: doughnutOpts,
    });

    make("chart-severity", {
      type: "doughnut",
      data: {
        labels: data.severity.labels,
        datasets: [{
          data: data.severity.counts,
          backgroundColor: data.severity.labels.map((label) => SEVERITY_COLORS[label]),
          borderWidth: 0,
        }],
      },
      options: doughnutOpts,
    });

    make("chart-priority", {
      type: "bar",
      data: {
        labels: data.priority.labels,
        datasets: [{
          data: data.priority.counts,
          backgroundColor: data.priority.labels.map((label) => PRIORITY_COLORS[label]),
          borderRadius: 4,
        }],
      },
      options: barOpts(false, false),
    });

    make("chart-aging", {
      type: "bar",
      data: {
        labels: data.aging.labels,
        datasets: [{ data: data.aging.counts, backgroundColor: AGING_COLORS, borderRadius: 4 }],
      },
      options: barOpts(false, false),
    });

    make("chart-workload", {
      type: "bar",
      data: {
        labels: data.workload.developers,
        datasets: SEVERITIES.map((severity) => ({
          label: severity,
          data: data.workload.series[severity],
          backgroundColor: SEVERITY_COLORS[severity],
          stack: "workload",
          borderRadius: 2,
        })),
      },
      options: barOpts(true, true),
    });

    make("chart-modules", {
      type: "bar",
      data: {
        labels: data.modules.labels,
        datasets: [{ data: data.modules.counts, backgroundColor: "#6610f2", borderRadius: 4 }],
      },
      options: barOpts(true, false),
    });

    make("chart-sprints", {
      type: "bar",
      data: {
        labels: data.sprints.labels,
        datasets: [
          { label: "Completed", data: data.sprints.done, backgroundColor: "#198754",
            stack: "sprint", borderRadius: 2 },
          { label: "Remaining", data: data.sprints.remaining, backgroundColor: "#adb5bd",
            stack: "sprint", borderRadius: 2 },
        ],
      },
      options: barOpts(false, true),
    });
  };

  build();

  new MutationObserver((mutations) => {
    if (mutations.some((m) => m.attributeName === "data-bs-theme")) build();
  }).observe(document.documentElement, { attributes: true });
})();
