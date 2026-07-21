/**
 * Developer profile: "assigned by status" bar chart.
 * Rebuilds on theme toggle so axis colors follow dark mode
 * (same approach as dashboard.js).
 */
(() => {
  "use strict";

  const holder = document.getElementById("dev-status-data");
  const canvas = document.getElementById("chart-dev-status");
  if (!holder || !canvas || typeof Chart === "undefined") return;

  const payload = JSON.parse(holder.textContent);
  const css = (name) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  let chart;
  const build = () => {
    if (chart) chart.destroy();
    chart = new Chart(canvas, {
      type: "bar",
      data: {
        labels: payload.labels,
        datasets: [{
          data: payload.counts,
          backgroundColor: payload.colors,
          borderRadius: 4,
        }],
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            ticks: { color: css("--bs-body-color"), autoSkip: false, maxRotation: 60 },
            grid: { display: false },
          },
          y: {
            beginAtZero: true,
            ticks: { color: css("--bs-body-color"), precision: 0 },
            grid: { color: css("--bs-border-color") || "rgba(128,128,128,.2)" },
          },
        },
      },
    });
  };

  build();
  new MutationObserver(build).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-bs-theme"],
  });
})();
