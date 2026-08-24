/* app.js — XSD Visualizer viewer logic */

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  schema: null,          // active schema (original or updated)
  originalSchema: null,  // original.json
  updatedSchema: null,   // schema-model.json
  viewMode: "updated",   // "original" | "updated" | "diff"
  lang: "en",            // "en" | "ka"
  diff: null,            // diff-model.json or null
  byId: {},              // id → node
  childrenOf: {},        // id → [child ids]
  rootId: null,
  expanded: new Set(),
  selected: null,
  searchQuery: "",
  matchedIds: new Set(),   // ids matching current search
  diffByPath: {},            // xmlPath → [changes]
  diffByNodeId: {},          // nodeId → [changes]
  removedByParentPath: {},   // parentXmlPath → [originalNodes]
  removedById: {},           // "removed:"+xmlPath → originalNode
  filters: {
    showXmlTags: false,
    mandatoryOnly: false,
    repeatingOnly: false,
    changedOnly: false,
    showRemoved: false,
  },
  loadToken: 0,
};

// ── Language helper ────────────────────────────────────────────────────────────
function getDoc(node) {
  if (state.lang === "ka" && node.documentationKA) return node.documentationKA;
  return node.documentation || null;
}

// ── Cache-busting ──────────────────────────────────────────────────────────────

/** Append ?v=BUILD_V to a URL when a build hash is available (set by version.js). */
function vUrl(url) {
  const v = window.__BUILD_V__;
  return v ? `${url}?v=${v}` : url;
}

// ── Bootstrap ──────────────────────────────────────────────────────────────────

/** Load a .js sidecar by injecting a <script> tag; captures and clears the global. */
function loadSidecar(url, globalVar) {
  return new Promise(resolve => {
    const script = document.createElement("script");
    script.src = url;
    script.onload = () => {
      const val = window[globalVar] ?? null;
      delete window[globalVar];
      resolve(val);
    };
    script.onerror = () => resolve(null);
    document.head.appendChild(script);
  });
}

async function fetchManifest() {
  try {
    const res = await fetch(vUrl("data/messages.json"));
    if (res.ok) return await res.json();
  } catch (e) { /* fall through */ }
  return window.__MESSAGES__ ?? null;
}

function populateSelector(messages) {
  const sel = document.getElementById("message-selector");
  sel.innerHTML = "";
  for (const msg of messages) {
    const opt = document.createElement("option");
    opt.value = msg.id;
    opt.textContent = msg.label;
    sel.appendChild(opt);
  }
  sel.addEventListener("change", () => loadData(sel.value));
}

async function loadData(messageId) {
  const token = ++state.loadToken;
  // Reset transient UI
  state.expanded    = new Set();
  state.selected    = null;
  state.searchQuery = "";
  state.matchedIds  = new Set();
  document.getElementById("search-box").value = "";
  document.getElementById("tree-body").innerHTML =
    '<div class="no-results" id="loading-msg">Loading schema…</div>';
  document.getElementById("diff-bar").classList.remove("visible");
  document.getElementById("cb-changed-wrap").style.display = "none";
  document.getElementById("cb-removed-wrap").style.display = "none";
  document.getElementById("view-selector").style.display   = "none";
  state.filters.changedOnly = false;
  state.filters.showRemoved = false;
  document.getElementById("cb-changed").checked = false;
  document.getElementById("cb-removed").checked = false;

  const prefix = `data/${messageId}`;

  // Try fetch for all three in parallel
  const [origRes, schemaRes, diffRes] = await Promise.allSettled([
    fetch(vUrl(`${prefix}/original.json`)),
    fetch(vUrl(`${prefix}/schema-model.json`)),
    fetch(vUrl(`${prefix}/diff-model.json`)),
  ]);

  if (token !== state.loadToken) return; // superseded by a newer load

  let originalSchema = null;
  if (origRes.status === "fulfilled" && origRes.value.ok)
    originalSchema = await origRes.value.json().catch(() => null);

  let updatedSchema = null;
  if (schemaRes.status === "fulfilled" && schemaRes.value.ok)
    updatedSchema = await schemaRes.value.json().catch(() => null);

  let diff = null;
  if (diffRes.status === "fulfilled" && diffRes.value.ok)
    diff = await diffRes.value.json().catch(() => null);

  // Sidecar fallbacks (file:// protocol) — sequential: shared globals
  if (!originalSchema) {
    originalSchema = await loadSidecar(`${prefix}/original.js`, "__SCHEMA_MODEL__");
    if (token !== state.loadToken) return;
  }
  if (!updatedSchema) {
    updatedSchema  = await loadSidecar(`${prefix}/schema-model.js`, "__SCHEMA_MODEL__");
    if (token !== state.loadToken) return;
  }
  if (!diff) {
    diff           = await loadSidecar(`${prefix}/diff-model.js`, "__DIFF_MODEL__");
    if (token !== state.loadToken) return;
  }

  if (!updatedSchema && !originalSchema) {
    document.getElementById("loading-msg").textContent =
      "Schema data not found. Run build.py first, then serve this folder via HTTP.";
    return;
  }

  state.originalSchema = originalSchema;
  state.updatedSchema  = updatedSchema;
  state.diff           = diff;

  // Default view
  if (diff && updatedSchema)  state.viewMode = "diff";
  else if (updatedSchema)     state.viewMode = "updated";
  else                        state.viewMode = "original";

  state.schema = state.viewMode === "original" ? originalSchema : updatedSchema;

  setupViewSelector();
  initIndex();
  if (state.diff && state.viewMode === "diff") initDiff();
  renderAll();
}

async function init() {
  const manifest = await fetchManifest();
  if (!manifest || !manifest.messages || manifest.messages.length === 0) {
    document.getElementById("loading-msg").textContent =
      "messages.json not found. Run build.py first, then serve this folder via HTTP.";
    return;
  }
  populateSelector(manifest.messages);
  bindUI();
  const defaultMsg = manifest.messages.find(m => m.id.startsWith("pain.001")) ?? manifest.messages[0];
  document.getElementById("message-selector").value = defaultMsg.id;
  await loadData(defaultMsg.id);
}

function setupViewSelector() {
  const sel    = document.getElementById("view-selector");
  const hasOrig = !!state.originalSchema;
  const hasUpd  = !!state.updatedSchema;
  const hasDiff = !!state.diff;

  if (!hasOrig && !hasDiff) return;

  sel.querySelector('[data-view="original"]').style.display = hasOrig ? "" : "none";
  sel.querySelector('[data-view="updated"]').style.display  = hasUpd  ? "" : "none";
  sel.querySelector('[data-view="diff"]').style.display     = hasDiff ? "" : "none";

  sel.style.display = "flex";
  _updateViewButtons();
}

function switchView(mode) {
  if (mode === state.viewMode) return;
  state.viewMode = mode;
  state.schema = (mode === "original") ? state.originalSchema : state.updatedSchema;

  // Reset transient UI state
  state.expanded  = new Set();
  state.selected  = null;
  state.searchQuery = "";
  state.matchedIds  = new Set();
  document.getElementById("search-box").value = "";

  initIndex();

  if (mode === "diff" && state.diff) {
    initDiff();
  } else {
    state.diffByPath   = {};
    state.diffByNodeId = {};
    state.removedByParentPath = {};
    state.removedById = {};
    document.getElementById("diff-bar").classList.remove("visible");
    document.getElementById("cb-changed-wrap").style.display = "none";
    document.getElementById("cb-removed-wrap").style.display = "none";
    state.filters.changedOnly = false;
    state.filters.showRemoved = false;
    document.getElementById("cb-changed").checked = false;
    document.getElementById("cb-removed").checked = false;
  }

  _updateViewButtons();
  renderAll();
}

function _updateViewButtons() {
  document.querySelectorAll(".view-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.view === state.viewMode);
  });
}

function initIndex() {
  const { nodesFlat } = state.schema;
  state.byId = {};
  state.childrenOf = {};

  for (const n of nodesFlat) {
    state.byId[n.id] = n;
    state.childrenOf[n.id] = [];
  }

  for (const n of nodesFlat) {
    if (n.parentId && state.childrenOf[n.parentId] !== undefined) {
      state.childrenOf[n.parentId].push(n.id);
    }
  }
  state.rootId = nodesFlat.find(n => n.parentId === null)?.id ?? null;

  // Expand root and first level by default
  if (state.rootId) {
    state.expanded.add(state.rootId);
    for (const cid of state.childrenOf[state.rootId] ?? []) {
      state.expanded.add(cid);
    }
  }

  // Update browser tab title
  const meta = state.schema.metadata;
  document.title = `XSD Visualizer — ${meta.messageName || meta.rootElement}`;
}

function initDiff() {
  state.diffByPath = {};
  state.diffByNodeId = {};
  state.removedByParentPath = {};
  state.removedById = {};

  for (const change of state.diff.changes) {
    if (!state.diffByPath[change.xmlPath]) state.diffByPath[change.xmlPath] = [];
    state.diffByPath[change.xmlPath].push(change);
  }
  // Map by nodeId
  for (const n of state.schema.nodesFlat) {
    if (state.diffByPath[n.xmlPath]) {
      state.diffByNodeId[n.id] = state.diffByPath[n.xmlPath];
    }
  }

  // Build removed ghost nodes from original schema
  if (state.originalSchema) {
    const removedPaths = new Set(
      state.diff.changes.filter(c => c.changeType === "RemovedNode").map(c => c.xmlPath)
    );
    const origByPath = {};
    for (const n of state.originalSchema.nodesFlat) origByPath[n.xmlPath] = n;

    for (const path of removedPaths) {
      // Skip if parent is also removed — the parent ghost covers the subtree
      const parentPath = path.substring(0, path.lastIndexOf("/")) || "/";
      if (removedPaths.has(parentPath)) continue;
      const origNode = origByPath[path];
      if (!origNode) continue;
      if (!state.removedByParentPath[parentPath]) state.removedByParentPath[parentPath] = [];
      state.removedByParentPath[parentPath].push(origNode);
      state.removedById["removed:" + path] = origNode;
    }
  }

  // Show diff bar
  const s = state.diff.summary;
  document.getElementById("dp-added").textContent   = `Added: ${s.added}`;
  document.getElementById("dp-removed").textContent = `Removed: ${s.removed}`;
  document.getElementById("dp-changed").textContent = `Changed: ${s.changed}`;
  document.getElementById("diff-bar").classList.add("visible");
  document.getElementById("cb-changed-wrap").style.display = "";
  document.getElementById("cb-removed-wrap").style.display = "";
}

// ── UI bindings ────────────────────────────────────────────────────────────────
function bindUI() {
  // View selector buttons (registered once; loadData resets active state via _updateViewButtons)
  document.querySelectorAll(".view-btn").forEach(btn => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });

  document.querySelectorAll(".lang-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      state.lang = btn.dataset.lang;
      document.querySelectorAll(".lang-btn").forEach(b => b.classList.toggle("active", b === btn));
      renderTree();
      if (state.selected) selectNode(state.selected);
    });
  });

  document.getElementById("btn-expand-all").addEventListener("click", () => {
    for (const id of Object.keys(state.childrenOf)) {
      if (state.childrenOf[id].length > 0) state.expanded.add(id);
    }
    renderTree();
  });
  document.getElementById("btn-collapse-all").addEventListener("click", () => {
    state.expanded.clear();
    if (state.rootId) state.expanded.add(state.rootId);
    renderTree();
  });

  const searchBox = document.getElementById("search-box");
  searchBox.addEventListener("input", () => {
    state.searchQuery = searchBox.value.trim().toLowerCase();
    applySearch();
    renderTree();
  });

  document.getElementById("cb-xml-tags").addEventListener("change", e => {
    state.filters.showXmlTags = e.target.checked;
    renderTree();
  });
  document.getElementById("cb-mandatory").addEventListener("change", e => {
    state.filters.mandatoryOnly = e.target.checked;
    renderTree();
  });
  document.getElementById("cb-repeating").addEventListener("change", e => {
    state.filters.repeatingOnly = e.target.checked;
    renderTree();
  });
  document.getElementById("cb-changed").addEventListener("change", e => {
    state.filters.changedOnly = e.target.checked;
    renderTree();
  });
  document.getElementById("cb-removed").addEventListener("change", e => {
    state.filters.showRemoved = e.target.checked;
    renderTree();
  });
}

// ── Search ─────────────────────────────────────────────────────────────────────
function applySearch() {
  state.matchedIds.clear();
  if (!state.searchQuery) return;

  for (const n of state.schema.nodesFlat) {
    const haystack = [
      n.label, n.name, n.xmlTag, n.xmlPath, n.typeName, n.documentation, n.documentationKA
    ].filter(Boolean).join(" ").toLowerCase();
    if (haystack.includes(state.searchQuery)) {
      state.matchedIds.add(n.id);
      // Expand all ancestors
      expandAncestors(n.id);
    }
  }
}

function expandAncestors(id) {
  const node = state.byId[id];
  if (!node || !node.parentId) return;
  state.expanded.add(node.parentId);
  expandAncestors(node.parentId);
}

// ── Filters ────────────────────────────────────────────────────────────────────
function isNodeVisible(node) {
  if (state.searchQuery && !state.matchedIds.has(node.id)) {
    // Also show ancestors of matched nodes (they're already expanded by applySearch)
    return false;
  }
  if (state.filters.mandatoryOnly && !node.isMandatory) return false;
  if (state.filters.repeatingOnly && !node.isRepeating) return false;
  if (state.filters.changedOnly && state.diff && !state.diffByNodeId[node.id]) return false;
  return true;
}

// ── Rendering ──────────────────────────────────────────────────────────────────
function renderAll() {
  renderTree();
}

function renderTree() {
  const container = document.getElementById("tree-body");
  const showTag = state.filters.showXmlTags;

  // Update header columns
  const hdr = document.getElementById("tree-header");
  if (showTag) {
    hdr.className = "with-tag";
    hdr.innerHTML = "<span>Name</span><span>XML Tag</span><span>Mult.</span><span>Type</span>";
  } else {
    hdr.className = "";
    hdr.innerHTML = "<span>Name</span><span>Mult.</span><span>Type</span>";
  }

  if (!state.rootId) return;
  const fragment = document.createDocumentFragment();

  // When search is active, show only matched nodes (flat, not tree)
  if (state.searchQuery && state.matchedIds.size > 0) {
    for (const id of state.matchedIds) {
      const node = state.byId[id];
      if (node) fragment.appendChild(buildRow(node, 0, showTag, true));
    }
  } else if (state.searchQuery && state.matchedIds.size === 0) {
    const d = document.createElement("div");
    d.className = "no-results";
    d.textContent = "No results found.";
    fragment.appendChild(d);
  } else {
    buildTreeRows(state.rootId, 0, fragment, showTag);
  }

  container.innerHTML = "";
  container.appendChild(fragment);
}

function buildTreeRows(id, depth, fragment, showTag) {
  const node = state.byId[id];
  if (!node) return;
  if (!isNodeVisible(node)) {
    // Even if this node is hidden, children might match — recurse if expanded
    if (state.expanded.has(id)) {
      for (const cid of state.childrenOf[id] ?? []) {
        buildTreeRows(cid, depth + 1, fragment, showTag);
      }
    }
    return;
  }

  fragment.appendChild(buildRow(node, depth, showTag, false));

  if (state.expanded.has(id)) {
    for (const cid of state.childrenOf[id] ?? []) {
      buildTreeRows(cid, depth + 1, fragment, showTag);
    }
    if (state.viewMode === "diff" && state.filters.showRemoved) {
      for (const rn of state.removedByParentPath[node.xmlPath] ?? []) {
        if (isRemovedNodeVisible(rn)) {
          fragment.appendChild(buildRemovedRow(rn, depth + 1, showTag));
        }
      }
    }
  }
}

function isRemovedNodeVisible(node) {
  if (!state.searchQuery) return true;
  const haystack = [node.label, node.name, node.xmlTag, node.xmlPath, node.typeName, node.documentation, node.documentationKA]
    .filter(Boolean).join(" ").toLowerCase();
  return haystack.includes(state.searchQuery);
}

function buildRemovedRow(origNode, depth, showTag) {
  const ghostId = "removed:" + origNode.xmlPath;
  const row = document.createElement("div");
  let cls = "tree-row diff-removed";
  if (showTag) cls += " with-tag";
  if (state.selected === ghostId) cls += " selected";
  row.className = cls;
  row.dataset.id = ghostId;
  const doc = state.lang === "ka" && origNode.documentationKA ? origNode.documentationKA : (origNode.documentation || null);
  if (doc) row.title = doc;

  const nameCell = document.createElement("div");
  nameCell.className = "tree-name-cell";

  const indent = document.createElement("span");
  indent.className = "tree-indent";
  indent.style.width = `${depth * 16 + 3}px`;
  nameCell.appendChild(indent);

  const nameSpan = document.createElement("span");
  nameSpan.className = "node-name";
  nameSpan.textContent = origNode.label || origNode.name;
  nameCell.appendChild(nameSpan);

  const badge = getBadge(origNode);
  if (badge) nameCell.appendChild(badge);

  const removedBadge = document.createElement("span");
  removedBadge.className = "diff-badge db-removed";
  removedBadge.textContent = "removed";
  nameCell.appendChild(removedBadge);

  row.appendChild(nameCell);

  if (showTag) {
    const tagCell = document.createElement("div");
    tagCell.className = "tree-xml-tag";
    tagCell.textContent = origNode.xmlTag;
    row.appendChild(tagCell);
  }

  const multCell = document.createElement("div");
  multCell.className = "tree-mult";
  multCell.textContent = origNode.multiplicity;
  row.appendChild(multCell);

  const typeCell = document.createElement("div");
  typeCell.className = "tree-type";
  typeCell.textContent = origNode.typeName || "";
  row.appendChild(typeCell);

  row.addEventListener("click", () => selectNode(ghostId));
  return row;
}

function buildRow(node, depth, showTag, flatSearch) {
  const row = document.createElement("div");
  const hasChildren = (state.childrenOf[node.id] ?? []).length > 0;
  const isExpanded = state.expanded.has(node.id);
  // CSS classes
  let cls = "tree-row";
  if (showTag) cls += " with-tag";
  if (node.id === state.selected) cls += " selected";
  if (state.diffByNodeId[node.id]) {
    const changes = state.diffByNodeId[node.id];
    const isBreaking = changes.some(c => c.severity === "Breaking");
    const types = new Set(changes.map(c => c.changeType));
    if (types.has("AddedNode"))   cls += " diff-added";
    else if (types.has("RemovedNode")) cls += " diff-removed";
    else cls += " diff-changed";
    if (isBreaking) cls += " diff-breaking";
  }
  row.className = cls;
  row.dataset.id = node.id;
  const doc = getDoc(node);
  if (doc) row.title = doc;

  // Name cell
  const nameCell = document.createElement("div");
  nameCell.className = "tree-name-cell";

  if (!flatSearch) {
    const indent = document.createElement("span");
    indent.className = "tree-indent";
    indent.style.width = `${depth * 16 + (hasChildren ? 0 : 3)}px`;
    nameCell.appendChild(indent);
  }

  if (hasChildren) {
    const toggle = document.createElement("span");
    toggle.className = "toggle-btn";
    toggle.textContent = isExpanded ? "▼" : "▶";
    toggle.addEventListener("click", e => {
      e.stopPropagation();
      toggleNode(node.id);
    });
    nameCell.appendChild(toggle);
  }

  // Name text — prefer ISO label (source="Name" annotation) over abbreviated XML tag
  const displayName = node.label || node.name;
  const nameSpan = document.createElement("span");
  nameSpan.className = "node-name";
  nameSpan.textContent = displayName;
  if (state.searchQuery) highlight(nameSpan, state.searchQuery);
  nameCell.appendChild(nameSpan);

  // Badge
  const badge = getBadge(node);
  if (badge) nameCell.appendChild(badge);

  // Documentation indicator
  if (node.documentation || node.documentationKA) {
    const docHint = document.createElement("span");
    docHint.className = "doc-hint";
    docHint.textContent = "ℹ";
    docHint.title = doc || "";
    nameCell.appendChild(docHint);
  }

  // Diff badge
  if (state.diffByNodeId[node.id]) {
    const diffBadge = makeDiffBadge(state.diffByNodeId[node.id]);
    nameCell.appendChild(diffBadge);
  }

  row.appendChild(nameCell);

  // XML tag column (conditional)
  if (showTag) {
    const tagCell = document.createElement("div");
    tagCell.className = "tree-xml-tag";
    tagCell.textContent = node.xmlTag;
    row.appendChild(tagCell);
  }

  // Multiplicity
  const multCell = document.createElement("div");
  multCell.className = "tree-mult";
  multCell.textContent = node.multiplicity;
  row.appendChild(multCell);

  // Type
  const typeCell = document.createElement("div");
  typeCell.className = "tree-type";
  typeCell.textContent = node.typeName || "";
  typeCell.title = node.typeName || "";
  row.appendChild(typeCell);

  row.addEventListener("click", () => {
    selectNode(node.id);
    if (hasChildren) toggleNode(node.id);
  });
  return row;
}

function getBadge(node) {
  const map = {
    root:        null,
    element:     null,
    complexType: null,
    simpleType:  null,
    choice:      ["CHC", "b-chc"],
    codeSet:     ["CODE", "b-code"],
    amount:      ["AMT",  "b-amt"],
    date:        ["DATE", "b-date"],
    boolean:     ["BOOL", "b-bool"],
    text:        ["TXT",  "b-txt"],
    attribute:   ["@",    "b-attr"],
    circularRef: ["REF",  "b-ref"],
  };
  const entry = map[node.nodeKind];
  if (!entry) {
    if (node.isChoice) {
      const b = document.createElement("span");
      b.className = "badge b-chc";
      b.textContent = "CHC";
      return b;
    }
    return null;
  }
  const b = document.createElement("span");
  b.className = `badge ${entry[1]}`;
  b.textContent = entry[0];
  return b;
}

function makeDiffBadge(changes) {
  const b = document.createElement("span");
  const types = new Set(changes.map(c => c.changeType));
  const isBreaking = changes.some(c => c.severity === "Breaking");
  if (types.has("AddedNode"))       { b.className = "diff-badge db-added";   b.textContent = "+"; }
  else if (types.has("RemovedNode")){ b.className = "diff-badge db-removed"; b.textContent = "−"; }
  else { b.className = "diff-badge " + (isBreaking ? "db-breaking" : "db-changed");
         b.textContent = isBreaking ? "⚠" : "~"; }
  return b;
}

function highlight(el, query) {
  const text = el.textContent;
  const idx = text.toLowerCase().indexOf(query);
  if (idx === -1) return;
  el.innerHTML =
    escapeHtml(text.slice(0, idx)) +
    `<mark class="hl">${escapeHtml(text.slice(idx, idx + query.length))}</mark>` +
    escapeHtml(text.slice(idx + query.length));
}

function escapeHtml(s) {
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// ── Expand / collapse ──────────────────────────────────────────────────────────
function toggleNode(id) {
  if (state.expanded.has(id)) state.expanded.delete(id);
  else state.expanded.add(id);
  renderTree();
}

// ── Selection + details ────────────────────────────────────────────────────────
function selectNode(id) {
  state.selected = id;
  renderTree();
  if (id.startsWith("removed:")) {
    renderDetails(state.removedById[id], true);
  } else {
    renderDetails(state.byId[id], false);
  }
}

function renderDetails(node, isRemoved = false) {
  const panel = document.getElementById("details-panel");
  if (!node) { panel.innerHTML = '<p class="empty-msg">Select a node.</p>'; return; }

  const changes = isRemoved ? [] : (state.diffByNodeId[node.id] ?? []);
  const removedBanner = isRemoved
    ? `<div style="background:#ffebee;border-left:4px solid #e53935;padding:8px 12px;margin-bottom:16px;border-radius:4px;font-size:12px;color:#c62828;font-weight:600;">
        REMOVED — this element exists in ISO 20022 but was removed from the Georgian profile
       </div>`
    : "";

  let html = removedBanner + `
    <div class="detail-section">
      <h3>Node</h3>
      ${node.label ? `<div class="detail-row"><span class="detail-label">Name</span>
        <span class="detail-value">${esc(node.label)}</span></div>` : ""}
      <div class="detail-row"><span class="detail-label">XML Tag</span>
        <span class="detail-value"><code>${esc(node.xmlTag)}</code></span></div>
      <div class="detail-row path-row">
        <span class="detail-label">XML Path</span>
        <span class="detail-value"><code id="path-val">${esc(node.xmlPath)}</code></span>
        <button class="copy-btn" id="copy-path-btn">Copy</button>
      </div>
      <div class="detail-row"><span class="detail-label">Multiplicity</span>
        <span class="detail-value">${esc(node.multiplicity)}</span></div>
      <div class="detail-row"><span class="detail-label">Mandatory</span>
        <span class="detail-value">${node.isMandatory ? "Yes" : "No"}</span></div>
      <div class="detail-row"><span class="detail-label">Repeating</span>
        <span class="detail-value">${node.isRepeating ? "Yes" : "No"}</span></div>
      <div class="detail-row"><span class="detail-label">Node Kind</span>
        <span class="detail-value">${esc(node.nodeKind)}</span></div>
      <div class="detail-row"><span class="detail-label">Type</span>
        <span class="detail-value">${esc(node.typeName || "—")}</span></div>
      <div class="detail-row"><span class="detail-label">Base Type</span>
        <span class="detail-value">${esc(node.baseType || "—")}</span></div>
      <div class="detail-row"><span class="detail-label">Children</span>
        <span class="detail-value">${(state.childrenOf[node.id] ?? []).length}</span></div>
    </div>`;

  const detailDoc = getDoc(node);
  if (detailDoc) {
    html += `<div class="detail-section"><h3>Documentation</h3>
      <div class="detail-value">${esc(detailDoc)}</div></div>`;
  }

  const hasRestrictions = node.restrictions &&
    Object.values(node.restrictions).some(v => v !== null);
  if (hasRestrictions) {
    html += `<div class="detail-section"><h3>Restrictions</h3>
      <table class="restriction-table">`;
    for (const [k, v] of Object.entries(node.restrictions)) {
      if (v !== null) html += `<tr><td>${esc(k)}</td><td>${esc(String(v))}</td></tr>`;
    }
    html += `</table></div>`;
  }

  if (node.enumerations && node.enumerations.length > 0) {
    html += `<div class="detail-section"><h3>Enumeration Values (${node.enumerations.length})</h3>
      <table class="enum-table">`;
    for (const v of node.enumerations) {
      html += `<tr><td>${esc(v)}</td></tr>`;
    }
    html += `</table></div>`;
  }

  if (changes.length > 0) {
    html += `<div class="detail-section"><h3>Changes (${changes.length})</h3>
      <ul class="change-list">`;
    for (const c of changes) {
      html += `<li class="change-${esc(c.severity)}">
        <span class="change-type-tag">${esc(c.changeType)}</span>
        ${c.severity !== "NonBreaking" ? `<span class="sev-tag sev-${esc(c.severity)}">${esc(c.severity)}</span>` : ""}
        ${c.oldValue !== null && c.oldValue !== undefined
          ? `<small>Before: <code>${esc(String(c.oldValue))}</code>
             → After: <code>${c.newValue != null ? esc(String(c.newValue)) : "—"}</code></small>`
          : esc(c.description)}
      </li>`;
    }
    html += `</ul></div>`;
  }

  panel.innerHTML = html;

  // Copy button
  document.getElementById("copy-path-btn")?.addEventListener("click", () => {
    navigator.clipboard.writeText(node.xmlPath).then(() => {
      const btn = document.getElementById("copy-path-btn");
      if (btn) { btn.textContent = "Copied!"; btn.classList.add("copied");
                 setTimeout(() => { btn.textContent = "Copy"; btn.classList.remove("copied"); }, 1500); }
    });
  });
}

function esc(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;");
}

// ── Entry point ────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", init);
