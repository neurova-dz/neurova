/* App shell: sidebar toggle, HTMX CSRF header, notification bell sync. */
(function () {
  "use strict";

  // --- Sidebar (mobile) ---
  var shell = document.getElementById("nv-app-shell");
  var toggle = document.getElementById("nv-sidebar-toggle");
  var backdrop = document.getElementById("nv-sidebar-backdrop");
  var sidebar = document.getElementById("nv-sidebar");
  if (shell && toggle && backdrop && sidebar) {
    function setOpen(open) {
      shell.classList.toggle("nv-sidebar-is-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute(
        "aria-label",
        open ? "Close navigation menu" : "Open navigation menu"
      );
      backdrop.hidden = !open;
    }
    toggle.addEventListener("click", function () {
      setOpen(!shell.classList.contains("nv-sidebar-is-open"));
    });
    backdrop.addEventListener("click", function () { setOpen(false); });
    sidebar.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        if (window.matchMedia("(max-width: 991.98px)").matches) setOpen(false);
      });
    });
    window.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && shell.classList.contains("nv-sidebar-is-open")) setOpen(false);
    });
    window.addEventListener("resize", function () {
      if (window.matchMedia("(min-width: 992px)").matches) setOpen(false);
    });
  }

  // --- HTMX CSRF header injection ---
  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  if (csrfMeta && window.htmx) {
    document.body.addEventListener("htmx:configRequest", function (evt) {
      var token = csrfMeta.getAttribute("content");
      if (token) evt.detail.headers["X-CSRFToken"] = token;
    });
  } else {
    // htmx may load after DOMContentLoaded; defer attaching the listener
    document.addEventListener("htmx:configRequest", function (evt) {
      if (csrfMeta) {
        evt.detail.headers["X-CSRFToken"] = csrfMeta.getAttribute("content");
      }
    });
  }

  // --- Notification bell badge state ---
  // The HTMX poll returns the new count as plain text; keep the count visible only when > 0.
  document.addEventListener("htmx:afterSwap", function (evt) {
    var node = document.getElementById("nv-bell-count");
    if (!node) return;
    var n = parseInt((node.textContent || "").trim(), 10) || 0;
    if (n > 0) node.classList.remove("d-none");
    else node.classList.add("d-none");
  });
})();
