/* CloudVault dashboard script: validation, upload with progress, listing, delete. */
(function () {
  'use strict';

  var form = document.getElementById('upload-form');
  if (!form) { return; }

  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrf = csrfMeta ? csrfMeta.content : '';
  var cfgEl = document.getElementById('config');
  var cfg = cfgEl ? JSON.parse(cfgEl.textContent) : { allowed: [], maxBytes: 0 };

  var fileInput = document.getElementById('file-input');
  var uploadBtn = document.getElementById('upload-btn');
  var progressWrap = document.getElementById('progress-wrap');
  var progressBar = document.getElementById('upload-progress');
  var progressText = document.getElementById('progress-text');
  var tbody = document.getElementById('files-body');
  var statusEl = document.getElementById('status');

  function showMessage(text, kind) {
    statusEl.textContent = text;
    statusEl.className = 'status ' + (kind || 'info');
    if (kind === 'error') {
      statusEl.setAttribute('role', 'alert');
    } else {
      statusEl.setAttribute('role', 'status');
    }
  }

  function clearMessage() {
    statusEl.textContent = '';
    statusEl.className = 'status';
  }

  function formatSize(n) {
    if (n < 1024) { return n + ' B'; }
    if (n < 1024 * 1024) { return (n / 1024).toFixed(1) + ' KB'; }
    return (n / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function pad(n) { return n < 10 ? '0' + n : String(n); }

  // Consistent format: YYYY-MM-DD HH:MM (local time).
  function formatDate(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) { return iso; }
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function safeJson(text) {
    try { return JSON.parse(text); } catch (e) { return null; }
  }

  function setProgress(pct) {
    progressBar.value = pct;
    progressText.textContent = pct + '%';
  }

  function showProgress() {
    setProgress(0);
    progressWrap.hidden = false;
  }

  function hideProgress() {
    progressWrap.hidden = true;
    setProgress(0);
  }

  function validateFile(file) {
    var dot = file.name.lastIndexOf('.');
    var ext = dot >= 0 ? file.name.slice(dot + 1).toLowerCase() : '';
    if (dot < 0 || cfg.allowed.indexOf(ext) === -1) {
      return 'File type not allowed. Allowed types: ' + cfg.allowed.join(', ') + '.';
    }
    if (file.size > cfg.maxBytes) {
      return 'File too large. Maximum size is ' + formatSize(cfg.maxBytes) + '.';
    }
    return null;
  }

  // Ask CloudVault for a signed upload URL (JSON only, no file content).
  async function requestUploadUrl(file) {
    var res;
    try {
      res = await fetch('/api/files/upload-url', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'X-CSRF-Token': csrf
        },
        body: JSON.stringify({ name: file.name, size: file.size })
      });
    } catch (e) {
      throw new Error('Network error. Check your connection and try again.');
    }
    if (res.status === 401) {
      window.location.href = '/login';
      throw new Error('Authentication required.');
    }
    var body = safeJson(await res.text());
    if (!res.ok || !body || !body.url) {
      throw new Error((body && body.error) || 'Could not start the upload.');
    }
    return body;
  }

  // PUT the file straight to Supabase Storage; the token is part of the URL.
  function putSigned(url, file) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      var data = new FormData();
      data.append('cacheControl', '3600');
      data.append('file', file);
      xhr.open('PUT', url);
      xhr.setRequestHeader('x-upsert', 'true');
      xhr.upload.onprogress = function (e) {
        if (e.lengthComputable) { setProgress(Math.round((e.loaded / e.total) * 100)); }
      };
      xhr.onload = function () {
        if (xhr.status === 200 || xhr.status === 201) {
          setProgress(100);
          resolve();
        } else {
          reject(new Error('Upload failed. Please try again.'));
        }
      };
      xhr.onerror = function () { reject(new Error('Network error during upload.')); };
      xhr.onabort = function () { reject(new Error('Upload was cancelled.')); };
      xhr.send(data);
    });
  }

  async function uploadFile(file) {
    var info = await requestUploadUrl(file);
    await putSigned(info.url, file);
    return info;
  }

  function isPreviewable(name) {
    var dot = name.lastIndexOf('.');
    var ext = dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
    return (cfg.previewable || []).indexOf(ext) !== -1;
  }

  function cell(label, child) {
    var td = document.createElement('td');
    td.setAttribute('data-label', label);
    if (typeof child === 'string') { td.textContent = child; } else if (child) { td.appendChild(child); }
    return td;
  }

  function renderEmpty() {
    tbody.textContent = '';
    var tr = document.createElement('tr');
    tr.id = 'empty-row';
    var td = document.createElement('td');
    td.colSpan = 4;
    td.className = 'empty-state';
    td.textContent = 'No files uploaded yet.';
    tr.appendChild(td);
    tbody.appendChild(tr);
  }

  function renderRow(f) {
    var tr = document.createElement('tr');

    var nameTd = cell('Name', f.name);
    nameTd.className = 'file-name';
    tr.appendChild(nameTd);
    tr.appendChild(cell('Size', formatSize(f.size)));
    tr.appendChild(cell('Uploaded', formatDate(f.uploaded_at)));

    var actions = document.createElement('div');
    actions.className = 'actions';

    if (isPreviewable(f.name)) {
      var view = document.createElement('a');
      view.className = 'btn btn-secondary btn-sm';
      view.href = '/api/files/' + encodeURIComponent(f.name) + '/view';
      view.target = '_blank';
      view.rel = 'noopener noreferrer';
      view.textContent = 'View';
      view.setAttribute('aria-label', 'View ' + f.name);
      actions.appendChild(view);
    } else {
      var nv = document.createElement('button');
      nv.type = 'button';
      nv.className = 'btn btn-secondary btn-sm';
      nv.disabled = true;
      nv.title = 'Preview not available for this file type';
      nv.textContent = 'Preview unavailable';
      nv.setAttribute('aria-label', 'Preview unavailable for ' + f.name);
      actions.appendChild(nv);
    }

    var dl = document.createElement('a');
    dl.className = 'btn btn-secondary btn-sm';
    dl.href = '/api/files/' + encodeURIComponent(f.name) + '/download';
    dl.textContent = 'Download';
    dl.setAttribute('aria-label', 'Download ' + f.name);
    actions.appendChild(dl);

    var del = document.createElement('button');
    del.type = 'button';
    del.className = 'btn btn-danger btn-sm';
    del.textContent = 'Delete';
    del.setAttribute('aria-label', 'Delete ' + f.name);
    del.addEventListener('click', function () { deleteFile(f.name, tr); });
    actions.appendChild(del);

    tr.appendChild(cell('Actions', actions));
    return tr;
  }

  function renderFiles(files) {
    if (!files.length) { renderEmpty(); return; }
    tbody.textContent = '';
    files.forEach(function (f) { tbody.appendChild(renderRow(f)); });
  }

  async function loadFiles() {
    try {
      var res = await fetch('/api/files', { headers: { 'Accept': 'application/json' } });
      if (res.status === 401) { window.location.href = '/login'; return; }
      var body = safeJson(await res.text());
      if (!res.ok) {
        showMessage((body && body.error) || 'Could not load files.', 'error');
        return;
      }
      renderFiles(body.files || []);
    } catch (e) {
      showMessage('Could not load files. Check your connection and try again.', 'error');
    }
  }

  async function deleteFile(name, row) {
    if (!window.confirm('Delete ' + name + '?')) { return; }
    try {
      var res = await fetch('/api/files/' + encodeURIComponent(name), {
        method: 'DELETE',
        headers: { 'X-CSRF-Token': csrf }
      });
      if (res.status === 401) { window.location.href = '/login'; return; }
      var body = safeJson(await res.text());
      if (!res.ok) {
        showMessage((body && body.error) || 'Delete failed.', 'error');
        return;
      }
      if (row && row.parentNode) { row.parentNode.removeChild(row); }
      if (!tbody.querySelector('tr')) { renderEmpty(); }
      showMessage('Deleted ' + name + '.', 'success');
    } catch (e) {
      showMessage('Delete failed. Check your connection and try again.', 'error');
    }
  }

  form.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    clearMessage();
    var file = fileInput.files && fileInput.files[0];
    if (!file) {
      showMessage('Please choose a file to upload.', 'error');
      return;
    }
    var problem = validateFile(file);
    if (problem) {
      showMessage(problem, 'error');
      return;
    }
    uploadBtn.disabled = true;
    showProgress();
    try {
      var result = await uploadFile(file);
      hideProgress();
      showMessage('Uploaded ' + ((result && result.name) || file.name) + '.', 'success');
      form.reset();
      await loadFiles();
    } catch (e) {
      hideProgress();
      showMessage(e.message, 'error');
    } finally {
      uploadBtn.disabled = false;
    }
  });

  loadFiles();
})();
