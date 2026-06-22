'use strict';

const state = {
  messages: [],
  xsdCache: {},
  depCache: {},
  validateFn: null,
  wasmReady: false,
  wasmError: null,
  detectedId: null,
  errorLineNums: new Set(), // lines that have errors (for cursor highlighting)
};

let validateDebounce = null;

async function init() {
  await loadMessages();
  populateSelector();
  bindUI();
  loadWasm();
}

// ── Data loading ───────────────────────────────────────────────────────────

async function loadMessages() {
  if (window.__MESSAGES__) {
    state.messages = window.__MESSAGES__.messages || [];
    return;
  }
  try {
    const r = await fetch('data/messages.json');
    const d = await r.json();
    state.messages = d.messages || [];
  } catch {
    state.messages = [];
  }
}

function populateSelector() {
  const sel = document.getElementById('xsd-selector');
  for (const m of state.messages) sel.appendChild(new Option(m.id, m.id));
}

async function loadWasm() {
  try {
    const mod = await import('./vendor/index-browser.mjs');
    state.validateFn = mod.validateXML;
    state.wasmReady = true;
  } catch (e) {
    state.wasmError = e.message || String(e);
  }
}

// Fetch GEO XSD + recursively resolve all xs:import dependencies.
async function fetchXsdWithDeps(id) {
  if (state.xsdCache[id]) return { main: state.xsdCache[id], preload: state.depCache[id] };
  const main = await fetchFile(`data/${id}/GEO_${id}.xsd`);
  const preload = [];
  await resolveImports(main, id, new Set(), preload);
  state.xsdCache[id] = main;
  state.depCache[id] = preload;
  return { main, preload };
}

async function fetchFile(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`Failed to fetch ${url} (HTTP ${r.status})`);
  return r.text();
}

async function resolveImports(xsdContent, id, seen, preload) {
  const doc = new DOMParser().parseFromString(xsdContent, 'text/xml');
  const imports = doc.getElementsByTagNameNS('http://www.w3.org/2001/XMLSchema', 'import');
  for (const imp of imports) {
    const loc = imp.getAttribute('schemaLocation');
    if (!loc || seen.has(loc)) continue;
    seen.add(loc);
    try {
      const content = await fetchFile(`data/${id}/${loc}`);
      preload.push({ fileName: loc, contents: content });
      await resolveImports(content, id, seen, preload);
    } catch { /* missing dep — xmllint will report it */ }
  }
}

// ── UI binding ─────────────────────────────────────────────────────────────

function bindUI() {
  const xmlInput = document.getElementById('xml-input');
  const xsdSel   = document.getElementById('xsd-selector');
  const overlay  = document.getElementById('editor-overlay');

  // Keep overlay in sync with textarea scroll via transform (not scrollTop — overlay has overflow:visible)
  xmlInput.addEventListener('scroll', syncOverlayScroll);

  // Cursor-line error highlighting
  xmlInput.addEventListener('click', onCursorMove);
  xmlInput.addEventListener('keyup', onCursorMove);

  xmlInput.addEventListener('input', () => {
    updateLineCount();
    tryAutoDetect();
    syncValidateBtn();
    clearOverlay();

    const xml = xmlInput.value.trim();
    if (!xml) { clearResults(); return; }

    if (isAutoValidate()) {
      clearTimeout(validateDebounce);
      validateDebounce = setTimeout(autoValidateIfReady, 1000);
    }
  });

  xmlInput.addEventListener('paste', () => {
    setTimeout(() => {
      updateLineCount();
      tryAutoDetect();
      syncValidateBtn();
      clearOverlay();
      if (isAutoValidate()) autoValidateIfReady();
    }, 80);
  });

  xsdSel.addEventListener('change', () => {
    xsdSel.dataset.auto = '';
    document.getElementById('auto-badge').style.display = 'none';
    document.getElementById('no-schema-note').style.display = 'none';
    syncValidateBtn();
    if (isAutoValidate()) autoValidateIfReady();
  });

  document.getElementById('btn-format').addEventListener('click', doFormat);
  document.getElementById('btn-validate').addEventListener('click', doValidate);

  document.getElementById('xml-upload').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      xmlInput.value = ev.target.result;
      updateLineCount();
      tryAutoDetect();
      syncValidateBtn();
      clearOverlay();
      setTimeout(() => { if (isAutoValidate()) autoValidateIfReady(); }, 80);
    };
    reader.readAsText(file, 'utf-8');
    e.target.value = '';
  });
}

function isAutoValidate() {
  return document.getElementById('cb-autovalidate').checked;
}

function autoValidateIfReady() {
  const xsdId  = document.getElementById('xsd-selector').value;
  const hasXml = document.getElementById('xml-input').value.trim().length > 0;
  if (hasXml && xsdId) doValidate();
}

function updateLineCount() {
  const xml = document.getElementById('xml-input').value;
  document.getElementById('line-count').textContent = xml ? `${xml.split('\n').length} lines` : '';
}

function syncValidateBtn() {
  document.getElementById('btn-validate').disabled =
    document.getElementById('xml-input').value.trim().length === 0;
}

// ── Auto-detect ────────────────────────────────────────────────────────────

function tryAutoDetect() {
  const xml   = document.getElementById('xml-input').value.trim();
  const sel   = document.getElementById('xsd-selector');
  const badge = document.getElementById('auto-badge');
  const note  = document.getElementById('no-schema-note');

  state.detectedId = null;
  if (!xml) { badge.style.display = 'none'; note.style.display = 'none'; return; }
  if (sel.value && !sel.dataset.auto) { badge.style.display = 'none'; note.style.display = 'none'; return; }

  try {
    const doc = new DOMParser().parseFromString(xml, 'text/xml');
    if (doc.querySelector('parsererror')) { badge.style.display = 'none'; return; }
    const ns = doc.documentElement.namespaceURI;
    if (ns) {
      // Match only if the full namespace URI exactly equals the GEO XSD's targetNamespace
      const match = state.messages.find(m => m.ns === ns);
      state.detectedId = ns; // keep full URI for error messaging
      if (match) {
        sel.value = match.id;
        sel.dataset.auto = '1';
        badge.style.display = 'inline';
        note.style.display = 'none';
      } else {
        sel.value = '';
        sel.dataset.auto = '';
        badge.style.display = 'none';
        note.textContent = `Detected namespace: ${ns} — no matching schema in library`;
        note.style.display = 'block';
      }
      return;
    }
  } catch { /* ignore */ }
  badge.style.display = 'none';
  note.style.display = 'none';
}

// ── Format XML ─────────────────────────────────────────────────────────────

function doFormat() {
  const el  = document.getElementById('xml-input');
  const xml = el.value.trim();
  if (!xml) return;
  const doc = new DOMParser().parseFromString(xml, 'text/xml');
  if (doc.querySelector('parsererror')) {
    setStatus('err', '✗', 'XML is not well-formed — cannot format');
    clearBadge();
    return;
  }
  el.value = indentXML(new XMLSerializer().serializeToString(doc));
  updateLineCount();
  clearOverlay();
}

function indentXML(xml) {
  let out = '', depth = 0;
  xml.replace(/>\s*</g, '>\n<').split('\n').forEach(raw => {
    const line = raw.trim();
    if (!line) return;
    if (/^<\//.test(line)) depth = Math.max(0, depth - 1);
    out += '  '.repeat(depth) + line + '\n';
    if (/^<[^/?!]/.test(line) && !line.endsWith('/>') && !/<\//.test(line)) depth++;
  });
  return out.trimEnd();
}

// ── Overlay line highlighting ──────────────────────────────────────────────

function syncOverlayScroll() {
  const ta = document.getElementById('xml-input');
  document.getElementById('editor-overlay').style.transform =
    `translateY(-${ta.scrollTop}px)`;
}

function clearOverlay() {
  const overlay = document.getElementById('editor-overlay');
  overlay.innerHTML = '';
  overlay.style.transform = '';
  state.errorLineNums = new Set();
}

function updateErrorOverlay(errorLineNums) {
  state.errorLineNums = errorLineNums;
  const overlay = document.getElementById('editor-overlay');
  const xml = document.getElementById('xml-input').value;
  if (!errorLineNums.size) { overlay.innerHTML = ''; overlay.style.transform = ''; return; }
  const lines = xml.split('\n');
  const frag = document.createDocumentFragment();
  lines.forEach((_, i) => {
    const div = document.createElement('div');
    div.className = 'ov-line' + (errorLineNums.has(i + 1) ? ' has-err' : '');
    div.textContent = '​'; // zero-width space keeps the div at correct height
    frag.appendChild(div);
  });
  overlay.innerHTML = '';
  overlay.appendChild(frag);
  syncOverlayScroll();
}

// ── Cursor-line error tracking ─────────────────────────────────────────────

function onCursorMove() {
  const ta = document.getElementById('xml-input');
  const lineNum = ta.value.substring(0, ta.selectionStart).split('\n').length;
  document.querySelectorAll('.err-item').forEach(el => el.classList.remove('cursor-active'));
  if (!state.errorLineNums.has(lineNum)) return;
  // Find the error item whose jump-btn has this line number
  const btn = document.querySelector(`.jump-btn[data-line="${lineNum}"]`);
  if (!btn) return;
  const item = btn.closest('.err-item');
  if (item) {
    item.classList.add('cursor-active');
    item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}

// ── Clear results ──────────────────────────────────────────────────────────

function clearResults() {
  document.getElementById('results-status').innerHTML = '<span class="st-idle">Paste XML and press Validate.</span>';
  document.getElementById('errors-list').innerHTML = '<div class="hint-msg">No results yet.</div>';
  document.getElementById('results-chips').innerHTML = '';
  clearBadge();
  clearOverlay();
}

function clearBadge() {
  const b = document.getElementById('val-badge');
  b.className = '';
  b.style.display = '';
  b.textContent = '';
}

function setBadge(type, text) {
  const b = document.getElementById('val-badge');
  b.textContent = text;
  b.style.display = '';
  b.className = type === 'ok' ? 'vb-ok' : 'vb-err';
}

// ── Validate ───────────────────────────────────────────────────────────────

async function doValidate() {
  const xmlStr = document.getElementById('xml-input').value.trim();
  if (!xmlStr) return;

  clearTimeout(validateDebounce);

  const btn = document.getElementById('btn-validate');
  btn.disabled = true;
  btn.textContent = 'Validating…';
  document.getElementById('results-chips').innerHTML = '';
  document.getElementById('errors-list').innerHTML = '';
  clearOverlay();
  clearBadge();

  try {
    // 1. Well-formedness
    const doc = new DOMParser().parseFromString(xmlStr, 'text/xml');
    const parseErr = doc.querySelector('parsererror');
    if (parseErr) {
      setStatus('err', '✗', 'Not well-formed XML');
      setBadge('err', '✗ Malformed');
      renderErrors([{ message: parseErr.textContent.trim(), loc: null }]);
      return;
    }

    // 2. XSD selection
    const xsdId = document.getElementById('xsd-selector').value;
    if (!xsdId) {
      if (state.detectedId) {
        setStatus('err', '✗', `No schema for "${state.detectedId}"`);
        setBadge('err', '✗ No schema');
        document.getElementById('errors-list').innerHTML =
          `<div class="hint-msg">Namespace detected: <code>${escHtml(state.detectedId)}</code><br>
           No matching schema available in this library.</div>`;
      } else {
        setStatus('info', '✓', 'Well-formed (no XSD selected)');
        setBadge('ok', '✓ Well-formed');
        document.getElementById('errors-list').innerHTML =
          '<div class="hint-msg">Select a GEO message type to validate against a schema.</div>';
      }
      return;
    }

    // 3. Fetch XSD + deps
    setStatus('loading', '', 'Fetching schema…');
    let xsdContent, preload;
    try {
      ({ main: xsdContent, preload } = await fetchXsdWithDeps(xsdId));
    } catch (e) {
      setStatus('err', '✗', 'Failed to load schema');
      setBadge('err', '✗ Schema error');
      renderErrors([{ message: e.message, loc: null }]);
      return;
    }

    // 4. Wait for WASM
    if (!state.wasmReady) {
      setStatus('loading', '', 'Loading validator (first run takes a moment)…');
      const deadline = Date.now() + 15000;
      while (!state.wasmReady && !state.wasmError && Date.now() < deadline)
        await new Promise(r => setTimeout(r, 300));
    }
    if (!state.wasmReady) {
      setStatus('err', '✗', 'Validator failed to load');
      setBadge('err', '✗ Load error');
      renderErrors([{ message: state.wasmError || 'Could not load WASM validator.', loc: null }]);
      return;
    }

    // 5. Run xmllint
    setStatus('loading', '', 'Validating…');
    const result = await state.validateFn({
      xml:    [{ fileName: 'input.xml',        contents: xmlStr }],
      schema: [{ fileName: `GEO_${xsdId}.xsd`, contents: xsdContent }],
      preload,
    });

    if (result.valid) {
      setStatus('ok', '✓', 'Valid');
      setBadge('ok', '✓ Valid');
      document.getElementById('results-chips').innerHTML = '<span class="cnt-chip cnt-ok">Valid</span>';
      document.getElementById('errors-list').innerHTML =
        '<div class="hint-msg">XML is valid against the selected schema.</div>';
      clearOverlay();
    } else {
      const errs = (result.errors || []).map(e => ({
        message: e.message || e.rawMessage || String(e),
        loc: e.loc || null,
      }));
      const n = errs.length;
      setStatus('err', '✗', `${n} error${n !== 1 ? 's' : ''} found`);
      setBadge('err', `✗ ${n} error${n !== 1 ? 's' : ''}`);
      document.getElementById('results-chips').innerHTML = `<span class="cnt-chip cnt-err">${n}</span>`;
      renderErrors(errs);
      // Highlight error lines in the editor
      const errorLines = new Set(errs.map(e => e.loc?.lineNumber).filter(Boolean));
      updateErrorOverlay(errorLines);
    }

  } catch (e) {
    setStatus('err', '✗', 'Validation failed');
    setBadge('err', '✗ Error');
    renderErrors([{ message: e.message || String(e), loc: null }]);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Validate';
    syncValidateBtn();
  }
}

// ── Rendering helpers ──────────────────────────────────────────────────────

function setStatus(type, icon, text) {
  const el = document.getElementById('results-status');
  const cls = { ok: 'st-ok', err: 'st-err', info: 'st-info', loading: 'st-loading' }[type] || 'st-loading';
  const iconHtml = icon ? `<span class="st-icon">${icon}</span>` : '';
  el.innerHTML = `<div class="${cls}">${iconHtml}${escHtml(text)}</div>`;
}

function renderErrors(errors) {
  const list = document.getElementById('errors-list');
  if (!errors.length) { list.innerHTML = ''; return; }
  list.innerHTML = errors.map(e => {
    const locHtml = e.loc
      ? `<div class="err-loc">Line ${e.loc.lineNumber}
           <button class="jump-btn" data-line="${e.loc.lineNumber}">jump</button>
         </div>`
      : '';
    return `<div class="err-item lv-error">
      <span class="err-badge eb-error">ERROR</span>
      ${locHtml}
      <div class="err-msg">${escHtml(e.message)}</div>
    </div>`;
  }).join('');
  list.querySelectorAll('.jump-btn').forEach(btn =>
    btn.addEventListener('click', () => jumpToLine(parseInt(btn.dataset.line, 10)))
  );
}

function jumpToLine(lineNum) {
  const ta = document.getElementById('xml-input');
  const lines = ta.value.split('\n');
  let pos = 0;
  for (let i = 0; i < Math.min(lineNum - 1, lines.length); i++) pos += lines[i].length + 1;
  ta.focus();
  ta.setSelectionRange(pos, pos + (lines[lineNum - 1] || '').length);
  const lh = parseFloat(getComputedStyle(ta).lineHeight) || 20;
  ta.scrollTop = Math.max(0, lineNum - 5) * lh;
  syncOverlayScroll();
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

init();
