/* Upload helpers: drag-drop, modality-aware validation, brain-modality slot UI.
 * Looks for a form with id="nv-upload-form" and standard inputs:
 *   - <select name="modality">
 *   - <input type="file" name="files" multiple>
 */
(function () {
  "use strict";
  var form = document.getElementById("nv-upload-form");
  if (!form) return;

  var modalitySel = form.querySelector('[name="modality"]');
  var modelTypeSel = form.querySelector('[name="model_type"]');
  var lateralitySel = form.querySelector('[name="laterality"]');
  var lateralityWrap = document.getElementById("nv-laterality-wrap");
  var fileInput = form.querySelector('input[type="file"][name="files"]');
  var dropzone = document.getElementById("nv-dropzone");
  var fileSummary = document.getElementById("nv-file-summary");
  var modalityHint = document.getElementById("nv-modality-hint");
  var brainSlots = document.getElementById("nv-brain-slots");

  function modalityRules(modality) {
    if (modality === "mri") {
      return {
        title: "Brain MRI / 4 NIfTI volumes",
        accept: ".nii,.nii.gz",
        min: 4, max: 4,
        showLaterality: false,
        message: "Drop the four structural series (t1c, t1n, t2f/FLAIR, t2w) — file names should contain those tags or be ordered.",
      };
    }
    if (modality === "retina_fundus") {
      return {
        title: "Retina fundus / single image",
        accept: ".png,.jpg,.jpeg,.tif,.tiff,.bmp",
        min: 1, max: 1,
        showLaterality: true,
        message: "Drop a single fundus photograph; pick the eye laterality.",
      };
    }
    return {
      title: "Pick a modality first",
      accept: "",
      min: 0, max: 0,
      showLaterality: false,
      message: "Pick the modality to see allowed file types.",
    };
  }

  function applyRules() {
    var mod = modalitySel ? modalitySel.value : "";
    var rules = modalityRules(mod);
    if (fileInput) {
      fileInput.accept = rules.accept;
      fileInput.multiple = rules.max > 1;
      fileInput.dataset.min = String(rules.min);
      fileInput.dataset.max = String(rules.max);
    }
    if (modalityHint) modalityHint.textContent = rules.message;
    if (lateralityWrap) lateralityWrap.style.display = rules.showLaterality ? "" : "none";
    if (modelTypeSel) {
      var v = mod === "mri" ? "brain_3d" : (mod === "retina_fundus" ? "diabetic_retinopathy" : "");
      modelTypeSel.value = v;
    }
    if (brainSlots) brainSlots.style.display = mod === "mri" ? "" : "none";
    summarize();
  }

  function summarize() {
    if (!fileSummary) return;
    var files = fileInput && fileInput.files ? Array.from(fileInput.files) : [];
    if (!files.length) {
      fileSummary.textContent = "No file selected.";
      return;
    }
    var bytes = files.reduce(function (a, f) { return a + (f.size || 0); }, 0);
    var mb = (bytes / (1024 * 1024)).toFixed(1);
    fileSummary.textContent = files.length + " file(s), " + mb + " MB total.";
    // brain slot mapping
    if (brainSlots && modalitySel && modalitySel.value === "mri") {
      var slots = ["t1c", "t1n", "t2f", "t2w"];
      slots.forEach(function (tag) {
        var el = document.getElementById("nv-slot-" + tag);
        if (!el) return;
        var match = files.find(function (f) {
          return f.name.toLowerCase().indexOf(tag) !== -1
            || (tag === "t2f" && f.name.toLowerCase().indexOf("flair") !== -1);
        });
        el.classList.toggle("nv-slot-filled", !!match);
        var text = el.querySelector(".nv-slot-file");
        if (text) text.textContent = match ? match.name : "(missing)";
      });
    }
  }

  function validateBeforeSubmit(evt) {
    var rules = modalityRules(modalitySel ? modalitySel.value : "");
    var n = fileInput && fileInput.files ? fileInput.files.length : 0;
    if (rules.min === 0 || n < rules.min || n > rules.max) {
      evt.preventDefault();
      alert("Please select " + rules.min + (rules.min === rules.max ? "" : "–" + rules.max) + " file(s) for this modality.");
      return false;
    }
    return true;
  }

  if (modalitySel) modalitySel.addEventListener("change", applyRules);
  if (fileInput) fileInput.addEventListener("change", summarize);
  form.addEventListener("submit", validateBeforeSubmit);

  if (dropzone && fileInput) {
    ["dragenter", "dragover"].forEach(function (ev) {
      dropzone.addEventListener(ev, function (e) {
        e.preventDefault(); e.stopPropagation();
        dropzone.classList.add("nv-dropzone--drag");
      });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      dropzone.addEventListener(ev, function (e) {
        e.preventDefault(); e.stopPropagation();
        dropzone.classList.remove("nv-dropzone--drag");
      });
    });
    dropzone.addEventListener("drop", function (e) {
      var dt = e.dataTransfer; if (!dt || !dt.files) return;
      try {
        fileInput.files = dt.files;
      } catch (_err) { /* some browsers disallow direct assign */ }
      summarize();
    });
    dropzone.addEventListener("click", function () { fileInput.click(); });
  }

  applyRules();
})();
