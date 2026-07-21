/**
 * User form behaviour: keep the username resembling the full name.
 * - create page (input has data-autofill="1"): live-derive the username
 *   from the full name until the admin edits the username by hand;
 * - edit page: the "Match name" button re-derives it on demand.
 */
(() => {
  "use strict";

  const fullName = document.getElementById("full_name");
  const username = document.getElementById("username");
  if (!fullName || !username) return;

  // "Krishna Pal" -> "krishna.pal"
  const derive = (value) =>
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9\s._-]/g, "")
      .split(/\s+/)
      .filter(Boolean)
      .join(".");

  if (username.dataset.autofill === "1") {
    let touched = username.value.trim() !== "";
    username.addEventListener("input", () => {
      touched = username.value.trim() !== "";
    });
    fullName.addEventListener("input", () => {
      if (!touched) username.value = derive(fullName.value);
    });
  }

  const syncBtn = document.getElementById("btn-sync-username");
  if (syncBtn) {
    syncBtn.addEventListener("click", () => {
      username.value = derive(fullName.value);
      username.focus();
    });
  }
})();
