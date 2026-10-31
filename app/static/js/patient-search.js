/* Client-side filter for patient roster tables. */
(function () {
  "use strict";
  var input = document.getElementById("nv-patient-search");
  var rows = document.querySelectorAll("[data-patient-row]");
  if (!input || !rows.length) return;
  function apply() {
    var q = (input.value || "").trim().toLowerCase();
    rows.forEach(function (row) {
      var hay = (row.dataset.search || row.textContent || "").toLowerCase();
      row.style.display = q && hay.indexOf(q) === -1 ? "none" : "";
    });
  }
  input.addEventListener("input", apply);
  apply();
})();
