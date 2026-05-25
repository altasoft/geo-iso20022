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
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
XSDS_DIR = ROOT / "xsds"
VIEWER_DATA_DIR = ROOT / "viewer" / "data"


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

    entries = []
    for msg in messages:
        try:
            entry = build_message(msg)
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
