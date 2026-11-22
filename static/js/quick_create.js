/*
 * "+" (new) and pencil (edit) buttons next to every <select data-quick-create>.
 * The partner form opens in a dialog; on save the select gets the new/updated
 * option and the user simply carries on with the form they were filling in.
 */
(function () {
  'use strict';
  var dialog, body, current;

  function ensureDialog() {
    if (dialog) return;
    dialog = document.createElement('dialog');
    dialog.className = 'quick-dialog';
    body = document.createElement('div');
    dialog.appendChild(body);
    document.body.appendChild(dialog);
    dialog.addEventListener('click', function (e) {
      if (e.target === dialog || e.target.closest('[data-quick-cancel]')) dialog.close();
    });
  }

  function show(html) {
    body.innerHTML = html;
    var form = body.querySelector('form');
    if (form) form.addEventListener('submit', submit);
    if (!dialog.open) dialog.showModal();
    var first = body.querySelector('input:not([type=hidden]), select, textarea');
    if (first) first.focus();
  }

  function load(url) {
    ensureDialog();
    current.url = url;
    fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.text(); })
      .then(show)
      .catch(function () { alert('تعذّر فتح النموذج، تحقق من الاتصال.'); });
  }

  function submit(e) {
    e.preventDefault();
    var form = e.target;
    var btn = form.querySelector('[type=submit]');
    if (btn) btn.disabled = true;
    fetch(current.url, {
      method: 'POST', body: new FormData(form), credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (r) {
      var json = (r.headers.get('content-type') || '').indexOf('application/json') !== -1;
      return (json ? r.json() : r.text()).then(function (data) { return { json: json, data: data }; });
    }).then(function (res) {
      if (!res.json) { show(res.data); return; }
      apply(res.data);
      dialog.close();
    }).catch(function () {
      if (btn) btn.disabled = false;
      alert('تعذّر الحفظ، تحقق من الاتصال.');
    });
  }

  function apply(data) {
    var select = current.select;
    var id = String(data.id);
    var opt = Array.prototype.find.call(select.options, function (o) { return o.value === id; });
    if (opt) {
      opt.textContent = data.label;
    } else {
      opt = new Option(data.label, id);
      select.add(opt);
    }
    select.value = id;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function button(label, title) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn btn-secondary btn-sm quick-btn';
    b.textContent = label;
    b.title = title;
    return b;
  }

  function enhance(select) {
    if (select.dataset.quickReady) return;
    select.dataset.quickReady = '1';
    var wrap = document.createElement('div');
    wrap.className = 'quick-field';
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);

    var add = button('+ جديد', 'إضافة اسم جديد');
    var edit = button('تعديل', 'تعديل الاسم المختار');
    wrap.appendChild(add);
    wrap.appendChild(edit);

    function sync() { edit.disabled = !select.value; }
    select.addEventListener('change', sync);
    sync();

    add.addEventListener('click', function () {
      current = { select: select };
      load(select.dataset.quickCreate);
    });
    edit.addEventListener('click', function () {
      if (!select.value) return;
      current = { select: select };
      load(select.dataset.quickEdit.replace(/\/0\/$/, '/' + encodeURIComponent(select.value) + '/'));
    });
  }

  function init(root) {
    (root || document).querySelectorAll('select[data-quick-create]').forEach(enhance);
  }

  document.addEventListener('DOMContentLoaded', function () { init(); });
  document.addEventListener('htmx:afterSwap', function (e) { init(e.target); });
})();
