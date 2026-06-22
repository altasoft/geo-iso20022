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
import hashlib
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).parent
XSDS_DIR = ROOT / "xsds"
VIEWER_DATA_DIR = ROOT / "viewer" / "data"
XSD_NS = "http://www.w3.org/2001/XMLSchema"


def build_ns_index() -> dict[str, Path]:
    """Map targetNamespace → XSD path across all xsds/ subfolders (GEO_ preferred)."""
    index: dict[str, Path] = {}
    for prefer_geo in (False, True):
        for xsd_file in sorted(XSDS_DIR.rglob("*.xsd")):
            if "revision" in xsd_file.name.lower():
                continue
            if xsd_file.name.startswith("GEO_") != prefer_geo:
                continue
            try:
                root = ET.parse(xsd_file).getroot()
                ns = root.get("targetNamespace")
                if ns:
                    index[ns] = xsd_file
            except ET.ParseError:
                pass
    return index


def copy_xsd_with_deps(src: Path, out_dir: Path, ns_index: dict[str, Path], seen: set | None = None) -> None:
    """Copy src XSD to out_dir, then recursively copy all xs:import dependencies."""
    if seen is None:
        seen = set()
    try:
        root = ET.parse(src).getroot()
    except ET.ParseError as e:
        print(f"  [WARN] Cannot parse {src.name}: {e}")
        return
    for imp in root.findall(f"{{{XSD_NS}}}import"):
        loc = imp.get("schemaLocation")
        ns  = imp.get("namespace", "")
        if not loc or loc in seen:
            continue
        seen.add(loc)
        # Prefer file with that exact name in the same source folder, else resolve by namespace
        dep_src = src.parent / loc if (src.parent / loc).exists() else ns_index.get(ns)
        if dep_src:
            shutil.copy(dep_src, out_dir / loc)
            print(f"  dep: {dep_src.name} -> {loc}")
            copy_xsd_with_deps(dep_src, out_dir, ns_index, seen)
        else:
            print(f"  [WARN] Cannot resolve import: schemaLocation={loc!r}  namespace={ns!r}")


def discover_messages() -> list[dict]:
    """Return list of {id, isoXsd, geoXsd} for each valid message folder."""
    if not XSDS_DIR.exists():
        return []
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
    try:
        subprocess.run([sys.executable, *args], check=True)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Parser failed (exit {e.returncode}): {' '.join(str(a) for a in args)}", file=sys.stderr)
        raise


def build_message(msg: dict, ns_index: dict) -> dict:
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

    # Copy GEO XSD + all xs:import dependencies into the output folder
    geo_xsd_src = Path(msg["geoXsd"])
    shutil.copy(geo_xsd_src, out_dir / f"GEO_{msg_id}.xsd")
    copy_xsd_with_deps(geo_xsd_src, out_dir, ns_index)

    # Extract targetNamespace from the GEO XSD for exact namespace matching in the validator
    geo_ns = None
    try:
        geo_ns = ET.parse(geo_xsd_src).getroot().get("targetNamespace")
    except ET.ParseError:
        pass

    return {"id": msg_id, "label": msg_id, "ns": geo_ns}


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


def write_version() -> str:
    """Hash app.js + styles.css + all generated data JSON files → write viewer/data/version.js."""
    viewer_dir = ROOT / "viewer"
    h = hashlib.sha256()
    # Hash the static code files
    for fname in ["app.js", "styles.css"]:
        p = viewer_dir / fname
        if p.exists():
            h.update(p.read_bytes())
    # Hash all generated data JSON files so data changes also bust the cache
    if VIEWER_DATA_DIR.exists():
        for p in sorted(VIEWER_DATA_DIR.rglob("*.json")):
            h.update(p.read_bytes())
    version = h.hexdigest()[:8]

    version_js = VIEWER_DATA_DIR / "version.js"
    with open(version_js, "w", encoding="utf-8") as f:
        f.write(f"window.__BUILD_V__ = '{version}';\n")
    print(f"Written: {version_js} (v={version})")
    return version


def main() -> None:
    print("=== XSD Visualizer — Build ===\n")
    messages = discover_messages()
    if not messages:
        print("[ERROR] No valid message folders found in xsds/")
        print("Each subfolder must contain <id>.xsd and GEO_<id>.xsd")
        sys.exit(1)

    ns_index = build_ns_index()
    entries = []
    for msg in messages:
        try:
            entry = build_message(msg, ns_index)
            entries.append(entry)
        except subprocess.CalledProcessError:
            print(f"[ERROR] Skipping '{msg['id']}' due to build failure", file=sys.stderr)

    write_manifest(entries)
    write_version()

    print(f"\n=== Done. {len(entries)} message(s) built ===")
    print("\nTo view: cd viewer && python -m http.server 8080")
    print("Then open: http://localhost:8080\n")


if __name__ == "__main__":
    main()
