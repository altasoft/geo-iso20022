#!/usr/bin/env python3
"""
diff_xsd.py — compare two schema-model.json files

Usage:
    python parser/diff_xsd.py --old old/schema-model.json --new new/schema-model.json --out viewer/diff-model.json
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


# ── Severity helpers ──────────────────────────────────────────────────────────

def _max_occurs_num(v: str) -> float:
    if v == "unbounded":
        return float("inf")
    try:
        return float(v)
    except (ValueError, TypeError):
        return 1.0


def _restriction_severity(old_val, new_val, facet: str) -> str:
    """All restriction changes are NonBreaking — the Georgian profile only tightens, never contradicts."""
    if old_val is None and new_val is None:
        return "Informational"
    return "NonBreaking"


# ── Matcher ───────────────────────────────────────────────────────────────────

def match_nodes(old_nodes: list[dict],
                new_nodes: list[dict]) -> list[tuple[dict | None, dict | None]]:
    old_by_path = {n["xmlPath"]: n for n in old_nodes}
    new_by_path = {n["xmlPath"]: n for n in new_nodes}
    matched_new: set[str] = set()
    pairs: list[tuple] = []

    for path, old in old_by_path.items():
        if path in new_by_path:
            pairs.append((old, new_by_path[path]))
            matched_new.add(path)
        else:
            parent = "/".join(path.split("/")[:-1])
            tag = path.split("/")[-1]
            candidate = next(
                (n for n in new_nodes
                 if "/".join(n["xmlPath"].split("/")[:-1]) == parent
                 and n["xmlTag"] == tag
                 and n["xmlPath"] not in matched_new),
                None,
            )
            if candidate:
                pairs.append((old, candidate))
                matched_new.add(candidate["xmlPath"])
            else:
                pairs.append((old, None))

    for path, new in new_by_path.items():
        if path not in matched_new:
            pairs.append((None, new))

    return pairs


# ── Change detection ──────────────────────────────────────────────────────────

def _change(change_type: str, severity: str, xml_path: str,
            old_val, new_val, description: str) -> dict:
    return {
        "changeType": change_type,
        "severity": severity,
        "xmlPath": xml_path,
        "oldValue": old_val,
        "newValue": new_val,
        "description": description,
    }


def compare_pair(old: dict | None, new: dict | None) -> list[dict]:
    if old is None and new is not None:
        sev = "Breaking" if new.get("isMandatory") else "NonBreaking"
        return [_change("AddedNode", sev, new["xmlPath"],
                        None, new["multiplicity"],
                        f"Node added: {new['xmlPath']} ({new['multiplicity']})")]

    if new is None and old is not None:
        return [_change("RemovedNode", "Informational", old["xmlPath"],
                        old["multiplicity"], None,
                        f"Node removed: {old['xmlPath']}")]

    changes = []
    path = new["xmlPath"]

    # minOccurs
    if old.get("minOccurs") != new.get("minOccurs"):
        changes.append(_change(
            "MinOccursChanged", "NonBreaking",
            path, str(old.get("minOccurs")), str(new.get("minOccurs")),
            f"minOccurs changed from {old.get('minOccurs')} to {new.get('minOccurs')}",
        ))

    # maxOccurs
    if old.get("maxOccurs") != new.get("maxOccurs"):
        old_max = _max_occurs_num(str(old.get("maxOccurs", "1")))
        new_max = _max_occurs_num(str(new.get("maxOccurs", "1")))
        changes.append(_change(
            "MaxOccursChanged", "NonBreaking",
            path, str(old.get("maxOccurs")), str(new.get("maxOccurs")),
            f"maxOccurs changed from {old.get('maxOccurs')} to {new.get('maxOccurs')}",
        ))

    # typeName
    if old.get("typeName") != new.get("typeName"):
        changes.append(_change(
            "TypeChanged", "NonBreaking",
            path, old.get("typeName"), new.get("typeName"),
            f"Type changed from {old.get('typeName')!r} to {new.get('typeName')!r}",
        ))

    # enumerations
    old_enums = set(old.get("enumerations") or [])
    new_enums = set(new.get("enumerations") or [])
    for v in sorted(old_enums - new_enums):
        changes.append(_change("EnumerationRemoved", "NonBreaking",
                               path, v, None, f"Enumeration value removed: {v!r}"))
    for v in sorted(new_enums - old_enums):
        changes.append(_change("EnumerationAdded", "NonBreaking",
                               path, None, v, f"Enumeration value added: {v!r}"))

    # restrictions
    old_r = old.get("restrictions") or {}
    new_r = new.get("restrictions") or {}
    for facet in ("pattern", "minLength", "maxLength", "length",
                  "totalDigits", "fractionDigits", "minInclusive"):
        ov, nv = old_r.get(facet), new_r.get(facet)
        if ov != nv:
            sev = _restriction_severity(ov, nv, facet)
            changes.append(_change(
                "RestrictionChanged", sev, path,
                f"{facet}={ov}", f"{facet}={nv}",
                f"Restriction {facet} changed from {ov!r} to {nv!r}",
            ))

    # isChoice
    if old.get("isChoice") != new.get("isChoice"):
        changes.append(_change(
            "ChoiceChanged", "NonBreaking", path,
            str(old.get("isChoice")), str(new.get("isChoice")),
            f"Choice structure changed: {old.get('isChoice')} → {new.get('isChoice')}",
        ))

    # documentation
    old_doc = (old.get("documentation") or "").strip()
    new_doc = (new.get("documentation") or "").strip()
    if old_doc != new_doc:
        changes.append(_change(
            "DocumentationChanged", "Informational", path,
            old_doc[:80], new_doc[:80], "Documentation text changed",
        ))

    return changes


def build_diff(old_model: dict, new_model: dict) -> dict:
    pairs = match_nodes(
        old_model.get("nodesFlat", []),
        new_model.get("nodesFlat", []),
    )
    all_changes: list[dict] = []
    for old, new in pairs:
        all_changes.extend(compare_pair(old, new))

    summary = {
        "added":         sum(1 for c in all_changes if c["changeType"] == "AddedNode"),
        "removed":       sum(1 for c in all_changes if c["changeType"] == "RemovedNode"),
        "changed":       sum(1 for c in all_changes if c["changeType"] not in ("AddedNode", "RemovedNode")),
        "breaking":      sum(1 for c in all_changes if c["severity"] == "Breaking"),
        "nonBreaking":   sum(1 for c in all_changes if c["severity"] == "NonBreaking"),
        "informational": sum(1 for c in all_changes if c["severity"] == "Informational"),
    }

    return {
        "metadata": {
            "oldSource": old_model.get("metadata", {}).get("sourceFile", ""),
            "newSource": new_model.get("metadata", {}).get("sourceFile", ""),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        },
        "summary": summary,
        "changes": all_changes,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Diff two schema-model.json files")
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.old, encoding="utf-8") as f:
        old_model = json.load(f)
    with open(args.new, encoding="utf-8") as f:
        new_model = json.load(f)

    diff = build_diff(old_model, new_model)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(diff, f, indent=2, ensure_ascii=False)

    js_path = out.with_suffix(".js")
    with open(js_path, "w", encoding="utf-8") as f:
        f.write("window.__DIFF_MODEL__ = ")
        json.dump(diff, f, ensure_ascii=False)
        f.write(";\n")

    print(f"Written: {out}")
    print(f"Summary: {diff['summary']}")


if __name__ == "__main__":
    main()
