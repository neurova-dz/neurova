/* Adaptive polling for inference jobs. */
(function () {
  "use strict";
  var node = document.getElementById("nv-job-poll");
  if (!node) return;
  var jobId = node.getAttribute("data-job-id");
  var statusUrl = node.getAttribute("data-status-url");
  var resultUrl = node.getAttribute("data-result-url");
  if (!jobId || !statusUrl) return;

  var POLL_MIN_MS = 5000;
  var POLL_MAX_MS = 10000;
  var currentDelay = POLL_MIN_MS;

  function setProgress(percent, stage, message) {
    var bar = document.getElementById("nv-progress-bar");
    var label = document.getElementById("nv-progress-label");
    var stageEl = document.getElementById("nv-progress-stage");
    if (bar) bar.style.width = (percent || 0) + "%";
    if (label) label.textContent = (percent || 0) + "%";
    if (stageEl) {
      stageEl.textContent = stage
        ? stage.replace(/_/g, " ") + (message ? " — " + message : "")
        : (message || "");
    }
  }

  function setStatus(status, errorCode, errorMessage) {
    var el = document.getElementById("nv-job-status");
    if (!el) return;
    el.dataset.status = status || "";
    el.textContent = status || "";
    var err = document.getElementById("nv-job-error");
    if (err) {
      if (status === "failed" || status === "timed_out" || status === "cancelled") {
        err.classList.remove("d-none");
        var code = document.getElementById("nv-job-error-code");
        var msg = document.getElementById("nv-job-error-message");
        if (code) code.textContent = errorCode || "unknown";
        if (msg) msg.textContent = errorMessage || "";
      } else {
        err.classList.add("d-none");
      }
    }
  }

  function poll() {
    fetch(statusUrl, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("status " + r.status);
        return r.json();
      })
      .then(function (data) {
        setProgress(data.progress, data.progress_stage, data.progress_message);
        setStatus(data.status, data.error_code, data.error_message);
        if (data.status === "done") {
          window.location.href = resultUrl;
          return;
        }
        if (data.status === "failed" || data.status === "timed_out" || data.status === "cancelled") {
          return; // stop polling
        }
        currentDelay = Math.min(POLL_MAX_MS, Math.max(POLL_MIN_MS, currentDelay));
        setTimeout(poll, currentDelay);
      })
      .catch(function () {
        currentDelay = Math.min(POLL_MAX_MS, currentDelay + 1000);
        setTimeout(poll, currentDelay);
      });
  }
  setTimeout(poll, 1500);
})();
