/**
 * Defect module behaviour:
 * - form page: the Feature select only shows features of the chosen Module;
 * - detail page: the transition form reveals resolution / duplicate fields
 *   only when the selected target status needs them.
 */
(() => {
  "use strict";

  // --- dependent feature select (defect form) -----------------------------
  const moduleSel = document.getElementById("module_id");
  const featureSel = document.getElementById("feature_id");
  if (moduleSel && featureSel) {
    const filterFeatures = () => {
      const moduleId = moduleSel.value;
      let selectionHidden = false;
      featureSel.querySelectorAll("option").forEach((opt) => {
        const belongs = !opt.dataset.module || opt.dataset.module === moduleId;
        opt.hidden = !belongs;
        if (!belongs && opt.selected) selectionHidden = true;
      });
      if (selectionHidden) featureSel.value = "0";
    };
    moduleSel.addEventListener("change", filterFeatures);
    filterFeatures();
  }

  // --- status transition form (defect detail) ------------------------------
  const statusSel = document.getElementById("to_status");
  if (statusSel) {
    const resolutionBlock = document.getElementById("resolution-block");
    const duplicateBlock = document.getElementById("duplicate-block");
    const sync = () => {
      const opt = statusSel.selectedOptions[0];
      const terminal = !!opt && opt.dataset.terminal === "1";
      const duplicate = !!opt && opt.dataset.duplicate === "1";
      if (resolutionBlock) resolutionBlock.classList.toggle("d-none", !terminal);
      if (duplicateBlock) duplicateBlock.classList.toggle("d-none", !duplicate);
    };
    statusSel.addEventListener("change", sync);
    sync();
  }
})();
