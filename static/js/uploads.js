/*
 * Upload widgets ([data-dropzone]): drag & drop, phone camera, file summary.
 *
 * - Dropping files puts them into the "choose files" input.
 * - Choosing photos with the camera input marks the upload as source=camera
 *   and ticks "combine into one PDF" when several pages were taken.
 * - Works with plain forms and HTMX forms; delegated so HTMX-swapped
 *   content needs no re-initialisation.
 */
(function () {
  function zoneOf(el) { return el.closest('[data-dropzone]'); }

  function summarise(zone) {
    var inputs = zone.querySelectorAll('[data-file-input]');
    var names = [];
    var camera = false;
    inputs.forEach(function (input) {
      Array.prototype.forEach.call(input.files || [], function (f) { names.push(f.name); });
      if (input.hasAttribute('data-camera') && input.files && input.files.length) camera = true;
    });
    var summary = zone.querySelector('[data-file-summary]');
    if (summary) {
      if (!summary.dataset.original) summary.dataset.original = summary.textContent;
      summary.textContent = names.length
        ? names.length + ' ملف: ' + names.slice(0, 4).join('، ') + (names.length > 4 ? '…' : '')
        : summary.dataset.original;
    }
    var source = zone.querySelector('[data-upload-source]');
    if (source) source.value = camera ? 'camera' : 'upload';
    var combine = zone.querySelector('[data-combine]');
    if (combine && camera && names.length > 1 && !combine.dataset.touched) combine.checked = true;
  }

  document.addEventListener('change', function (e) {
    if (e.target.matches('[data-combine]')) e.target.dataset.touched = '1';
    if (!e.target.matches('[data-file-input]')) return;
    var zone = zoneOf(e.target);
    if (zone) summarise(zone);
  });

  document.addEventListener('reset', function (e) {
    var zone = e.target.matches && e.target.matches('[data-dropzone]') ? e.target : null;
    if (zone) setTimeout(function () { summarise(zone); }, 0);
  }, true);

  ['dragenter', 'dragover'].forEach(function (type) {
    document.addEventListener(type, function (e) {
      var target = e.target.closest && e.target.closest('[data-dropzone-target]');
      if (!target) return;
      e.preventDefault();
      target.classList.add('is-dragover');
    });
  });
  ['dragleave', 'drop'].forEach(function (type) {
    document.addEventListener(type, function (e) {
      var target = e.target.closest && e.target.closest('[data-dropzone-target]');
      if (target) target.classList.remove('is-dragover');
    });
  });
  document.addEventListener('drop', function (e) {
    var target = e.target.closest && e.target.closest('[data-dropzone-target]');
    if (!target || !e.dataTransfer || !e.dataTransfer.files.length) return;
    e.preventDefault();
    var zone = zoneOf(target);
    var input = zone.querySelector('[data-file-input]:not([data-camera])');
    if (!input) return;
    try {
      var dt = new DataTransfer();
      Array.prototype.forEach.call(input.files || [], function (f) { dt.items.add(f); });
      Array.prototype.forEach.call(e.dataTransfer.files, function (f) { dt.items.add(f); });
      input.files = dt.files;
    } catch (err) {
      input.files = e.dataTransfer.files; // older browsers: replace selection
    }
    summarise(zone);
  });
})();
