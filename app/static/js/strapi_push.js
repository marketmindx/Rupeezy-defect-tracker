/**
 * "Create as Bug in Strapi" dialog — shared by the defect form (pending
 * mode, before the defect is saved), and the defect list / detail pages
 * (existing mode, defect already has an id).
 *
 * Every field is optional — nothing is required, nothing pre-selected.
 * Leaving the user story number blank sends the bug straight to the
 * assignee's Backlog (no parent, no sprint). The assignee list is fetched
 * live so it always reflects the current board.
 */
(() => {
  "use strict";

  const PENDING_KEY = "dt-pending-strapi-push";
  const modalEl = document.getElementById("strapiPushModal");
  if (!modalEl) return; // partial not included on this page

  const el = {
    modal: modalEl,
    context: document.getElementById("strapi-modal-context"),
    error: document.getElementById("strapi-modal-error"),
    storyKey: document.getElementById("strapi-story-key"),
    sprint: document.getElementById("strapi-sprint"),
    assignee: document.getElementById("strapi-assignee"),
    points: document.getElementById("strapi-points"),
    labels: document.getElementById("strapi-labels"),
    confirm: document.getElementById("strapi-modal-confirm"),
    confirmLabel: document.getElementById("strapi-modal-confirm-label"),
    spinner: document.getElementById("strapi-modal-spinner"),
  };
  const bsModal = new bootstrap.Modal(el.modal);
  const csrfToken = document.getElementById("strapi-csrf-token").value;

  let current = null; // { mode, defectId, onSaved }
  let membersLoaded = false;

  function showAlert(kind, message) {
    const mount = document.getElementById("js-alert-mount");
    if (!mount) return;
    const div = document.createElement("div");
    div.className = `alert alert-${kind} alert-dismissible fade show`;
    div.role = "alert";
    div.textContent = message;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn-close";
    btn.setAttribute("data-bs-dismiss", "alert");
    div.appendChild(btn);
    mount.appendChild(div);
    setTimeout(() => bootstrap.Alert.getOrCreateInstance(div).close(), 8000);
  }

  function resetForm() {
    el.error.classList.add("d-none");
    el.error.textContent = "";
    el.storyKey.value = "";
    el.sprint.value = "";
    el.assignee.value = "";
    el.points.value = "";
    el.labels.value = "";
    setBusy(false);
  }

  function setBusy(busy) {
    el.confirm.disabled = busy;
    el.spinner.classList.toggle("d-none", !busy);
    el.confirmLabel.textContent = busy ? "Working…" : "Create in Strapi";
  }

  async function loadMembers() {
    if (membersLoaded) return;
    try {
      const res = await fetch("/defects/strapi/members");
      const body = await res.json();
      if (!body.success) throw new Error(body.error?.message || "Could not load members.");
      el.assignee.querySelectorAll("option:not(:first-child)").forEach((o) => o.remove());
      body.data.forEach((m) => {
        const opt = document.createElement("option");
        opt.value = m.id;
        opt.textContent = `${m.name} (${m.team || "—"})`;
        el.assignee.appendChild(opt);
      });
      membersLoaded = true;
    } catch (err) {
      el.error.textContent = `Could not load Strapi members: ${err.message}`;
      el.error.classList.remove("d-none");
    }
  }

  function collect() {
    // Every field is optional. Blank sprint (or a blank story number) means
    // Backlog — see StrapiPushService.push for the server-side rule.
    return {
      story_key: el.storyKey.value.trim(),
      sprint_id: el.sprint.value ? Number(el.sprint.value) : null,
      assignee_member_id: el.assignee.value ? Number(el.assignee.value) : null,
      points: el.points.value ? Number(el.points.value) : null,
      labels: el.labels.value.split(",").map((s) => s.trim()).filter(Boolean),
    };
  }

  function describeResult(result) {
    return result.story_key
      ? `Created ${result.ticket_id} in Strapi, under ${result.story_key}.`
      : `Created ${result.ticket_id} in Strapi, in the assignee's Backlog.`;
  }

  async function pushExisting(defectId, payload) {
    const res = await fetch(`/defects/${defectId}/push-to-strapi`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    if (!body.success) throw new Error(body.error?.message || "Strapi push failed.");
    return body.data;
  }

  el.confirm.addEventListener("click", async () => {
    if (!current) return;
    const payload = collect();
    el.error.classList.add("d-none");

    if (current.mode === "pending") {
      sessionStorage.setItem(PENDING_KEY, JSON.stringify(payload));
      current.onSaved?.(payload);
      bsModal.hide();
      return;
    }

    setBusy(true);
    try {
      const result = await pushExisting(current.defectId, payload);
      bsModal.hide();
      showAlert("success", describeResult(result));
      current.onSuccess?.(result);
    } catch (err) {
      el.error.textContent = err.message;
      el.error.classList.remove("d-none");
    } finally {
      setBusy(false);
    }
  });

  el.modal.addEventListener("hidden.bs.modal", () => {
    if (current?.mode === "pending" && !sessionStorage.getItem(PENDING_KEY)) {
      current.onCancelled?.();
    }
    current = null;
  });

  function open(options) {
    current = options;
    resetForm();
    el.context.textContent = options.contextText || "";
    loadMembers();
    bsModal.show();
  }

  // -- public API ------------------------------------------------------------
  window.StrapiPush = {
    openForExisting(defectId, contextText, onSuccess) {
      open({ mode: "existing", defectId, contextText, onSuccess });
    },
    openForPending(contextText, onSaved, onCancelled) {
      open({ mode: "pending", contextText, onSaved, onCancelled });
    },
    /** Call on the detail page after a redirect from "Report defect" — fires
     * the queued push (if any) now that the defect has a real id. */
    async firePendingIfAny(defectId) {
      const raw = sessionStorage.getItem(PENDING_KEY);
      if (!raw) return;
      sessionStorage.removeItem(PENDING_KEY);
      try {
        const result = await pushExisting(defectId, JSON.parse(raw));
        showAlert("success", describeResult(result));
        setTimeout(() => window.location.reload(), 1200);
      } catch (err) {
        showAlert("danger", `Defect saved, but the Strapi push failed: ${err.message} — use "Create in Strapi" below to retry.`);
      }
    },
  };
})();
