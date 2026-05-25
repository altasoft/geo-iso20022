# Multi-Message Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the XSD Visualizer to support multiple ISO 20022 message types via a dropdown selector, auto-discovered from `xsds/` subfolders.

**Architecture:** Each message type lives in `xsds/<id>/` containing its ISO and `GEO_` XSD. `build.py` scans these folders, runs the existing parsers, and writes per-message JSON to `viewer/data/<id>/` plus a `messages.json` manifest. The viewer fetches the manifest on load, builds the dropdown, and dynamically loads the selected message's data.

**Tech Stack:** Python 3.10+ (build script), vanilla HTML/CSS/JS (viewer), lxml (existing parser dep)

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `build.py` | Auto-discover messages, run parsers, write manifest |
| Modify | `generate.bat` | Thin wrapper: `python build.py` |
| Create | `xsds/pain.001.001.09/` | Move all existing XSDs here |
| Delete | `viewer/original.json` + `.js` | Replaced by `viewer/data/pain.001.001.09/original.*` |
| Delete | `viewer/schema-model.json` + `.js` | Replaced by per-message folder |
| Delete | `viewer/diff-model.json` + `.js` | Replaced by per-message folder |
| Modify | `viewer/index.html` | Add `<select id="message-selector">`, update sidecar scripts |
| Modify | `viewer/app.js` | Manifest fetch, `loadData(messageId)`, selector wiring, move view-btn listeners to `bindUI()` |
| Modify | `viewer/styles.css` | Style `#message-selector` |
| Modify | `.github/workflows/deploy.yml` | Replace hardcoded parser calls with `python build.py` |

---

## Task 1: Migrate XSD Files Into Subfolder

**Files:**
- Create dir: `xsds/pain.001.001.09/`
- Move: all `xsds/*.xsd` → `xsds/pain.001.001.09/`

- [ ] **Step 1: Create the subfolder and move files**

```powershell
cd "D:\ALTASOFT\Pain001 analysis\GeorgianXsd\xsd-visualizer"
New-Item -ItemType Directory -Path "xsds\pain.001.001.09" -Force
Move-Item xsds\*.xsd xsds\pain.001.001.09\
```

- [ ] **Step 2: Verify the result**

```powershell
Get-ChildItem xsds\pain.001.001.09\
```

Expected output — five files:
```
pain.001.001.09.xsd
GEO_pain.001.001.09.xsd
GEO_pain.001.001.09.revision_0.3.xsd
GEO_pain.001.001.09.revision_0.4.xsd
GEO_pain.001.001.09.revision_0.5.xsd
```

---

## Task 2: Write `build.py`

**Files:**
- Create: `build.py`

- [ ] **Step 1: Create `build.py`**

```python
#!/usr/bin/env python3
"""
build.py — Auto-discover message folders in xsds/ and generate viewer data.

Usage:
    python build.py

Discovery rule: a subfolder of xsds/ is a valid message if it contains both
  <folder-name>.xsd  (ISO original)
  GEO_<folder-name>.xsd  (Georgian adaptation)

Output:
  viewer/data/<message-id>/original.json + .js
  viewer/data/<message-id>/schema-model.json + .js
  viewer/data/<message-id>/diff-model.json + .js
  viewer/data/messages.json + messages.js  (manifest)
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
XSDS_DIR = ROOT / "xsds"
VIEWER_DATA_DIR = ROOT / "viewer" / "data"


def discover_messages() -> list[dict]:
    """Return list of {id, isoXsd, geoXsd} for each valid message folder."""
    messages = []
    for folder in sorted(XSDS_DIR.iterdir()):
        if not folder.is_dir():
            continue
        msg_id = folder.name
        iso_xsd = folder / f"{msg_id}.xsd"
        geo_xsd = folder / f"GEO_{msg_id}.xsd"
        if iso_xsd.exists() and geo_xsd.exists():
            messages.append({"id": msg_id, "isoXsd": str(iso_xsd), "geoXsd": str(geo_xsd)})
        else:
            missing = []
            if not iso_xsd.exists():
                missing.append(iso_xsd.name)
            if not geo_xsd.exists():
                missing.append(geo_xsd.name)
            print(f"[WARN] Skipping '{msg_id}': missing {', '.join(missing)}")
    return messages


def run_parser(args: list[str]) -> None:
    """Run a parser subprocess; raise on non-zero exit."""
    subprocess.run([sys.executable, *args], check=True)


def build_message(msg: dict) -> dict:
    """Parse ISO + GEO XSDs and generate diff for one message. Returns manifest entry."""
    msg_id = msg["id"]
    out_dir = VIEWER_DATA_DIR / msg_id
    out_dir.mkdir(parents=True, exist_ok=True)

    original_json = str(out_dir / "original.json")
    schema_json   = str(out_dir / "schema-model.json")
    diff_json     = str(out_dir / "diff-model.json")

    print(f"\n[{msg_id}] (1/3) Parsing ISO original...")
    run_parser(["parser/parse_xsd.py", "--input", msg["isoXsd"], "--out", original_json])

    print(f"[{msg_id}] (2/3) Parsing Georgian revision...")
    run_parser(["parser/parse_xsd.py", "--input", msg["geoXsd"], "--out", schema_json])

    print(f"[{msg_id}] (3/3) Generating diff...")
    run_parser(["parser/diff_xsd.py", "--old", original_json, "--new", schema_json, "--out", diff_json])

    return {"id": msg_id, "label": msg_id}


def write_manifest(entries: list[dict]) -> None:
    """Write messages.json and messages.js sidecar to viewer/data/."""
    VIEWER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"messages": entries}

    json_path = VIEWER_DATA_DIR / "messages.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"\nWritten: {json_path}")

    js_path = VIEWER_DATA_DIR / "messages.js"
    with open(js_path, "w", encoding="utf-8") as f:
        f.write("window.__MESSAGES__ = ")
        json.dump(manifest, f, ensure_ascii=False)
        f.write(";\n")
    print(f"Written: {js_path}")


def main() -> None:
    print("=== XSD Visualizer — Build ===\n")
    messages = discover_messages()
    if not messages:
        print("[ERROR] No valid message folders found in xsds/")
        print("Each subfolder must contain <id>.xsd and GEO_<id>.xsd")
        sys.exit(1)

    entries = []
    for msg in messages:
        entry = build_message(msg)
        entries.append(entry)

    write_manifest(entries)

    print(f"\n=== Done. {len(entries)} message(s) built ===")
    print("\nTo view: cd viewer && python -m http.server 8080")
    print("Then open: http://localhost:8080\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run `build.py` to verify it works**

```powershell
cd "D:\ALTASOFT\Pain001 analysis\GeorgianXsd\xsd-visualizer"
python build.py
```

Expected output (truncated):
```
=== XSD Visualizer — Build ===

[pain.001.001.09] (1/3) Parsing ISO original...
Written: viewer\data\pain.001.001.09\original.json
Written: viewer\data\pain.001.001.09\original.js
[pain.001.001.09] (2/3) Parsing Georgian revision...
Written: viewer\data\pain.001.001.09\schema-model.json
...
[pain.001.001.09] (3/3) Generating diff...
Written: viewer\data\pain.001.001.09\diff-model.json
...
Written: viewer\data\messages.json
Written: viewer\data\messages.js

=== Done. 1 message(s) built ===
```

- [ ] **Step 3: Verify output structure**

```powershell
Get-ChildItem viewer\data\ -Recurse | Select-Object FullName
```

Expected — eight files under `viewer/data/`:
```
viewer\data\messages.json
viewer\data\messages.js
viewer\data\pain.001.001.09\original.json
viewer\data\pain.001.001.09\original.js
viewer\data\pain.001.001.09\schema-model.json
viewer\data\pain.001.001.09\schema-model.js
viewer\data\pain.001.001.09\diff-model.json
viewer\data\pain.001.001.09\diff-model.js
```

- [ ] **Step 4: Spot-check `messages.json`**

```powershell
Get-Content viewer\data\messages.json
```

Expected:
```json
{
  "messages": [
    {
      "id": "pain.001.001.09",
      "label": "pain.001.001.09"
    }
  ]
}
```

---

## Task 3: Update `generate.bat`

**Files:**
- Modify: `generate.bat`

- [ ] **Step 1: Replace contents of `generate.bat`**

```batch
@echo off
cd /d "%~dp0"
python build.py
pause
```

- [ ] **Step 2: Verify it runs**

```powershell
.\generate.bat
```

Expected: same output as running `python build.py` directly, followed by a pause prompt.

---

## Task 4: Delete Old Viewer Root Data Files

**Files:**
- Delete: `viewer/original.json`, `viewer/original.js`, `viewer/schema-model.json`, `viewer/schema-model.js`, `viewer/diff-model.json`, `viewer/diff-model.js`

- [ ] **Step 1: Delete the six old files**

```powershell
Remove-Item viewer\original.json, viewer\original.js, `
            viewer\schema-model.json, viewer\schema-model.js, `
            viewer\diff-model.json, viewer\diff-model.js -ErrorAction SilentlyContinue
```

- [ ] **Step 2: Confirm they're gone**

```powershell
Get-ChildItem viewer\*.json, viewer\*.js
```

Expected: no output (no JSON/JS files in viewer root — only in `viewer/data/`).

---

## Task 5: Update `viewer/index.html`

**Files:**
- Modify: `viewer/index.html`

- [ ] **Step 1: Add message selector to the header and update sidecar scripts**

Replace the entire contents of `viewer/index.html` with:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>XSD Visualizer</title>
  <link rel="stylesheet" href="styles.css"/>
</head>
<body>

<!-- Header -->
<div id="header">
  <span id="message-name">XSD Visualizer</span>
  <select id="message-selector" class="hdr-btn hidden"></select>
  <div id="lang-selector" style="gap:2px; display:flex">
    <button class="hdr-btn lang-btn active" data-lang="en">EN</button>
    <button class="hdr-btn lang-btn" data-lang="ka">KA</button>
  </div>
  <div id="view-selector" style="display:none; gap:2px">
    <button class="hdr-btn view-btn" data-view="original">ISO 20022</button>
    <button class="hdr-btn view-btn" data-view="updated">Georgian</button>
    <button class="hdr-btn view-btn" data-view="diff">Diff</button>
  </div>
  <input id="search-box" type="search" placeholder="Search name, path, type, documentation…"/>
  <button class="hdr-btn" id="btn-expand-all">Expand All</button>
  <button class="hdr-btn" id="btn-collapse-all">Collapse All</button>
</div>

<!-- Toolbar -->
<div id="toolbar">
  <label class="cb-label">
    <input type="checkbox" id="cb-xml-tags"/> Show XML Tags
  </label>
  <label class="cb-label">
    <input type="checkbox" id="cb-mandatory"/> Mandatory only
  </label>
  <label class="cb-label">
    <input type="checkbox" id="cb-repeating"/> Repeating only
  </label>
  <label class="cb-label" id="cb-changed-wrap" style="display:none">
    <input type="checkbox" id="cb-changed"/> Changed only
  </label>
  <label class="cb-label" id="cb-removed-wrap" style="display:none">
    <input type="checkbox" id="cb-removed" checked/> Show removed
  </label>
</div>

<!-- Diff summary bar -->
<div id="diff-bar">
  <strong>Changes:</strong>
  <span class="diff-pill dp-added"  id="dp-added">Added: 0</span>
  <span class="diff-pill dp-removed" id="dp-removed">Removed: 0</span>
  <span class="diff-pill dp-changed" id="dp-changed">Changed: 0</span>
</div>

<!-- Main -->
<div id="main">
  <!-- Tree panel -->
  <div id="tree-panel">
    <div id="tree-header">
      <span>Name</span>
      <span>Mult.</span>
      <span>Type</span>
    </div>
    <div id="tree-body">
      <div class="no-results" id="loading-msg">Loading schema…</div>
    </div>
  </div>

  <!-- Details panel -->
  <div id="details-panel">
    <p class="empty-msg">Select a node in the tree to view details.</p>
  </div>
</div>

<!-- Manifest sidecar fallback (for file:// protocol) -->
<script src="data/messages.js" onerror="void(0)"></script>
<script src="app.js"></script>
</body>
</html>
```

---

## Task 6: Update `viewer/app.js`

**Files:**
- Modify: `viewer/app.js`

The key changes:
1. `loadData()` becomes `loadData(messageId)` — all paths derived from `messageId`
2. New `init()` function: fetch manifest → populate selector → call `loadData(messages[0].id)` → `bindUI()`
3. New `loadSidecar(url, globalVar)` helper for `file://` fallback
4. `setupViewSelector()` — remove event listener registration (moved to `bindUI()`)
5. `bindUI()` — add view-button listeners, add search-box initial reset

- [ ] **Step 1: Replace the Bootstrap section in `app.js`**

Find and replace from the comment `// ── Bootstrap` through the closing `}` of `function setupViewSelector()` (i.e., old `loadData`, old `setupViewSelector` — stop before `function switchView`). **Everything from `function switchView` onward stays unchanged until Step 3.**

```javascript
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
    const res = await fetch("data/messages.json");
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
  if (messages.length <= 1) {
    sel.classList.add("hidden");
  } else {
    sel.classList.remove("hidden");
  }
  sel.addEventListener("change", () => loadData(sel.value));
}

async function loadData(messageId) {
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
  state.filters.showRemoved = true;
  document.getElementById("cb-changed").checked = false;
  document.getElementById("cb-removed").checked = true;

  const prefix = `data/${messageId}`;

  // Try fetch for all three in parallel
  const [origRes, schemaRes, diffRes] = await Promise.allSettled([
    fetch(`${prefix}/original.json`),
    fetch(`${prefix}/schema-model.json`),
    fetch(`${prefix}/diff-model.json`),
  ]);

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
  if (!originalSchema)
    originalSchema = await loadSidecar(`${prefix}/original.js`, "__SCHEMA_MODEL__");
  if (!updatedSchema)
    updatedSchema  = await loadSidecar(`${prefix}/schema-model.js`, "__SCHEMA_MODEL__");
  if (!diff)
    diff           = await loadSidecar(`${prefix}/diff-model.js`, "__DIFF_MODEL__");

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
  await loadData(manifest.messages[0].id);
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
```

- [ ] **Step 2: Replace `function switchView` — no logic change, just verify it doesn't call `setupViewSelector` (it doesn't, so leave unchanged)**

No edit needed for `switchView`. It is correct as-is.

- [ ] **Step 3: Replace `function bindUI()` in `app.js`**

Find and replace the entire `bindUI` function (currently lines 226–275):

```javascript
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
```

- [ ] **Step 4: Replace the entry point at the bottom of `app.js`**

Find:
```javascript
// ── Entry point ────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", loadData);
```

Replace with:
```javascript
// ── Entry point ────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", init);
```

---

## Task 7: Update `viewer/styles.css`

**Files:**
- Modify: `viewer/styles.css`

- [ ] **Step 1: Add message selector styles**

Find the end of the `/* ── Header ───` section — the line `.lang-btn.active { ... }` (currently line 28). Insert the following block immediately after it:

```css
/* Message selector */
#message-selector {
  padding: 5px 10px; border-radius: 4px; border: 1px solid #3f4769;
  background: #2a2d4a; color: #e8eaf6; font-size: 12px; cursor: pointer;
  height: 30px;
}
#message-selector:focus { outline: none; border-color: #7986cb; }
#message-selector option { background: #2a2d4a; color: #e8eaf6; }
#message-selector.hidden { display: none; }
```

---

## Task 8: Update `.github/workflows/deploy.yml`

**Files:**
- Modify: `.github/workflows/deploy.yml`

- [ ] **Step 1: Replace the three hardcoded parse steps with a single `build.py` call**

Find and remove these three steps:
```yaml
      - name: Parse ISO 20022 original
        run: python parser/parse_xsd.py --input xsds/pain.001.001.09.xsd --out viewer/original.json

      - name: Parse Georgian revision
        run: python parser/parse_xsd.py --input xsds/GEO_pain.001.001.09.xsd --out viewer/schema-model.json

      - name: Generate diff
        run: python parser/diff_xsd.py --old viewer/original.json --new viewer/schema-model.json --out viewer/diff-model.json
```

Replace with:
```yaml
      - name: Build viewer data
        run: python build.py
```

- [ ] **Step 2: Verify full deploy.yml looks correct**

The complete file after edit:

```yaml
name: Deploy to GitHub Pages

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Build viewer data
        run: python build.py

      - uses: actions/configure-pages@v5

      - uses: actions/upload-pages-artifact@v3
        with:
          path: ./viewer

      - id: deployment
        uses: actions/deploy-pages@v4
```

---

## Task 9: End-to-End Verification

- [ ] **Step 1: Run the existing test suite to confirm parsers still work**

```powershell
cd "D:\ALTASOFT\Pain001 analysis\GeorgianXsd\xsd-visualizer"
pytest tests/ -v
```

Expected: all tests pass (test suite uses `samples/` fixtures, not `xsds/`, so the folder move doesn't affect them).

- [ ] **Step 2: Serve the viewer locally and open it**

```powershell
cd viewer
python -m http.server 8080
```

Open `http://localhost:8080` in a browser.

Expected:
- Page loads without console errors
- The schema tree renders automatically (pain.001.001.09 data loads)
- If only one message is available, the `#message-selector` is hidden
- Language buttons, view buttons (ISO 20022 / Georgian / Diff), search, and filters all work

- [ ] **Step 3: Smoke-test the selector with a dummy second message folder**

```powershell
# Stop the server first (Ctrl+C), then:
New-Item -ItemType Directory -Path "xsds\test.999.999.99" -Force
Copy-Item xsds\pain.001.001.09\pain.001.001.09.xsd   xsds\test.999.999.99\test.999.999.99.xsd
Copy-Item xsds\pain.001.001.09\GEO_pain.001.001.09.xsd xsds\test.999.999.99\GEO_test.999.999.99.xsd
python ..\build.py
```

Expected: build output shows two messages processed; `viewer/data/` has both `pain.001.001.09/` and `test.999.999.99/`; `messages.json` lists both.

Serve again and confirm:
- Dropdown is now visible with two options
- Switching between them reloads the tree

- [ ] **Step 4: Clean up the dummy folder**

```powershell
Remove-Item -Recurse -Force xsds\test.999.999.99
Remove-Item -Recurse -Force viewer\data\test.999.999.99
python ..\build.py   # regenerate manifest with only pain.001.001.09
```

Expected: back to one message, manifest updated, dropdown hidden again.
