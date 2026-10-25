// Copyright (c) 2026 Domestique contributors
// SPDX-License-Identifier: Apache-2.0
(() => {
  if (window.__domestiqueAndroid) return;
  window.__domestiqueAndroid = true;
  const style = document.createElement('style');
  style.textContent = `
    #setup-connect-btn, #icu-connect-btn { display: none !important; }
    @media (max-width: 600px) {
      .container { padding: 8px; }
      header { flex-wrap: wrap; gap: 10px; }
      .header-stats { flex-wrap: wrap; gap: 12px; }
      .grid.g2, .grid.g3, .grid.g4 { grid-template-columns: minmax(0, 1fr); }
      .card { padding: 12px; min-width: 0; overflow-x: auto; }
      .tabs { position: sticky; top: 0; z-index: 20; }
      .tab { min-height: 44px; display: flex; align-items: center; }
      input, select, textarea { font-size: 16px !important; max-width: 100%; }
      button, .btn { min-height: 44px; }
      .wizard { padding: 24px 16px; border-radius: 0; }
      .modal { max-width: 100vw !important; width: 100% !important;
               max-height: 92vh !important; overflow-y: auto; }
    }
  `;
  document.head.appendChild(style);

  const setupStatus = document.getElementById('setup-link-status');
  if (setupStatus) setupStatus.textContent =
    'Android preview: continue without intervals.icu, then connect using your API key in Settings.';
  const connection = document.getElementById('icu-oauth-block');
  if (connection) {
    const help = document.getElementById('icu-conn-help');
    if (help) help.textContent = 'Android preview uses your personal API key to connect.';
    const form = document.createElement('div');
    form.innerHTML = `
      <p>Find your API key in <a href="https://intervals.icu/settings" target="_blank"
        rel="noopener">Intervals.icu Settings → Developer settings</a>.</p>
      <label for="android-icu-key">Intervals.icu API key</label>
      <input id="android-icu-key" type="password" autocomplete="off" spellcheck="false"
        style="width:100%;margin:8px 0;padding:10px;" />
      <button type="button" class="btn btn-primary">Connect with API key</button>
      <p role="status" aria-live="polite" style="margin-top:8px;"></p>`;
    const button = form.querySelector('button');
    const status = form.querySelector('[role=status]');
    const input = form.querySelector('input');
    button.onclick = async () => {
      const key = input.value.trim();
      if (!key) { status.textContent = 'Enter your API key.'; return; }
      button.disabled = true;
      status.textContent = 'Checking your connection…';
      try {
        const post = async (path, body) => {
          const response = await fetch(path, { method: 'POST',
            headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
          const data = await response.json();
          if (!response.ok) throw new Error(data.detail || 'Connection failed');
          return data;
        };
        const check = await post('/api/setup/test-icu', { api_key: key });
        if (!check.ok || !check.athlete_id) throw new Error(check.error || 'Could not identify your athlete.');
        const saved = await post('/api/setup/save', {
          icu_api_key: key, icu_athlete_id: check.athlete_id });
        if (!saved.ok || (saved.creds_test && saved.creds_test !== 'passed')) {
          throw new Error('Credentials saved, but verification failed. Please check your key.');
        }
        input.value = '';
        status.textContent = `Connected as ${check.name || check.athlete_id}.`;
        if (typeof window.loadIcuConnection === 'function') window.loadIcuConnection();
      } catch (error) { status.textContent = error.message; }
      finally { button.disabled = false; }
    };
    connection.appendChild(form);
  }

  // Existing exports create Blob URLs and click an <a download>. WebView does
  // not save these itself: hand the bytes to Android's Create Document picker.
  const blobs = new Map();
  const create = URL.createObjectURL.bind(URL);
  const revoke = URL.revokeObjectURL.bind(URL);
  URL.createObjectURL = blob => {
    const url = create(blob);
    blobs.set(url, blob);
    return url;
  };
  URL.revokeObjectURL = url => { blobs.delete(url); revoke(url); };

  function saveBlob(blob, name) {
    if (blob.size > 32 * 1024 * 1024) {
      alert('This export exceeds the Android preview limit of 32 MB.');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => window.DomestiqueAndroid.save(
      name || 'workout', String(reader.result).split(',')[1],
      blob.type || 'application/octet-stream');
    reader.onerror = () => alert('Could not read the export. Please try again.');
    reader.readAsDataURL(blob);
  }

  function download(anchor) {
    const url = new URL(anchor.href, location.href);
    const blob = blobs.get(url.href);
    if (blob) { saveBlob(blob, anchor.download); return true; }
    if (url.origin !== location.origin || !anchor.hasAttribute('download')) return false;
    fetch(url).then(response => {
      if (!response.ok) throw new Error('Download failed');
      return response.blob();
    }).then(data => saveBlob(data, anchor.download || url.pathname.split('/').pop()))
      .catch(() => alert('Could not download the file. Please try again.'));
    return true;
  }

  const click = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (!download(this)) return click.call(this);
  };
  document.addEventListener('click', event => {
    const anchor = event.target.closest && event.target.closest('a[download]');
    if (anchor && download(anchor)) { event.preventDefault(); event.stopImmediatePropagation(); }
  }, true);

  const open = window.open.bind(window);
  window.open = function (url, ...args) {
    const parsed = new URL(url || '', location.href);
    if (parsed.origin === location.origin && parsed.pathname.startsWith('/api/download/')) {
      const anchor = document.createElement('a');
      anchor.href = parsed.href;
      anchor.download = decodeURIComponent(parsed.pathname.split('/').pop());
      download(anchor);
      return null;
    }
    return open(url, ...args);
  };
})();
