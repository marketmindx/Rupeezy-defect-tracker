/**
 * App-shell behaviour: dark-mode toggle, tooltips, flash auto-dismiss.
 * The initial theme is applied by an inline snippet in <head> (pre-paint);
 * this file only keeps the UI in sync afterwards.
 */
(() => {
  "use strict";

  const THEME_KEY = "dt-theme";
  const root = document.documentElement;

  const applyTheme = (theme) => {
    root.setAttribute("data-bs-theme", theme);
    const icon = document.querySelector("#theme-toggle i");
    if (icon) {
      icon.className = theme === "dark" ? "bi bi-sun" : "bi bi-moon-stars";
    }
  };

  document.addEventListener("DOMContentLoaded", () => {
    applyTheme(root.getAttribute("data-bs-theme") || "light");

    const toggle = document.getElementById("theme-toggle");
    if (toggle) {
      toggle.addEventListener("click", () => {
        const next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
        localStorage.setItem(THEME_KEY, next);
        applyTheme(next);
      });
    }

    if (window.bootstrap) {
      document
        .querySelectorAll('[data-bs-toggle="tooltip"]')
        .forEach((el) => new bootstrap.Tooltip(el));

      document.querySelectorAll(".alert-auto-dismiss").forEach((el) => {
        setTimeout(() => bootstrap.Alert.getOrCreateInstance(el).close(), 6000);
      });
    }
  });
})();
