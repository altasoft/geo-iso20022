#!/usr/bin/env python3
"""
parse_xsd.py — XSD -> schema-model.json

Usage:
    python parser/parse_xsd.py --input ./samples/pacs.008.xsd --out ./viewer/schema-model.json
    python parser/parse_xsd.py --input ./samples/pacs.008.xsd --imports ./samples/ --out ./viewer/schema-model.json
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))
from schema_model import TypeRegistry, NodeBuilder, _strip_ns

XS = "http://www.w3.org/2001/XMLSchema"


def _xs(tag: str) -> str:
    return f"{{{XS}}}{tag}"


def extract_message_name(source_file: str) -> str:
    stem = Path(source_file).stem
    m = re.search(r'([a-z]{2,6}\.\d{3}\.\d{3}\.\d{2,3})', stem)
    return m.group(1) if m else stem


def load_schema(input_path: str, imports_dir: str | None,
                warnings: list) -> etree._Element:
    try:
        tree = etree.parse(input_path)
    except etree.XMLSyntaxError as e:
        sys.exit(f"[ERROR] Cannot parse {input_path}: {e}")
    root = tree.getroot()
    if imports_dir:
        imp_dir = Path(imports_dir)
        tags = [_xs("include"), _xs("import")]
        for tag in tags:
            for el in root.findall(f".//{tag}"):
                loc = el.get("schemaLocation")
                if not loc:
                    continue
                candidate = imp_dir / Path(loc).name
                if candidate.exists():
                    try:
                        imported = etree.parse(str(candidate))
                    except etree.XMLSyntaxError as e:
                        warnings.append(f"Cannot parse import {loc}: {e}")
                        continue
                    for child in imported.getroot():
                        root.append(child)
                else:
                    warnings.append(f"Cannot resolve: {loc}")
    return root


def find_root_element(schema_el) -> tuple[str, str] | None:
    for child in schema_el:
        if child.tag == etree.Comment:
            continue
        if etree.QName(child.tag).localname == "element":
            name = child.get("name")
            if name:
                return name, _strip_ns(child.get("type", name))
    return None


def _strip_children_from_flat(node: dict) -> dict:
    return {k: v for k, v in node.items() if k != "children"}


def _slim_tree(node: dict) -> dict:
    return {
        "id": node["id"],
        "name": node["name"],
        "xmlTag": node["xmlTag"],
        "xmlPath": node["xmlPath"],
        "nodeKind": node["nodeKind"],
        "multiplicity": node["multiplicity"],
        "children": [_slim_tree(c) for c in node.get("children", [])],
    }


def build_model(input_path: str, imports_dir: str | None = None) -> dict:
    warnings: list[str] = []
    schema_el = load_schema(input_path, imports_dir, warnings)

    target_ns = schema_el.get("targetNamespace", "")
    registry = TypeRegistry(warnings)
    registry.load_tree(schema_el)

    root_info = find_root_element(schema_el)
    if not root_info:
        raise ValueError("No top-level xs:element found in schema.")

    root_name, root_type = root_info
    builder = NodeBuilder(registry, warnings)
    tree_with_children = builder.build(root_name, root_type)

    nodes_flat = [_strip_children_from_flat(n) for n in builder.nodes_flat]

    return {
        "metadata": {
            "sourceFile": Path(input_path).name,
            "targetNamespace": target_ns,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rootElement": root_name,
            "messageName": extract_message_name(input_path),
            "warnings": warnings,
        },
        "nodesFlat": nodes_flat,
        "tree": _slim_tree(tree_with_children),
    }


def write_outputs(model: dict, out_path: str) -> None:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2, ensure_ascii=False)
    print(f"Written: {out}")

    js_path = out.with_suffix(".js")
    with open(js_path, "w", encoding="utf-8") as f:
        f.write("window.__SCHEMA_MODEL__ = ")
        json.dump(model, f, ensure_ascii=False)
        f.write(";\n")
    print(f"Written: {js_path}")

    if model["metadata"]["warnings"]:
        print(f"\nWarnings ({len(model['metadata']['warnings'])}):")
        for w in model["metadata"]["warnings"]:
            print(f"  [WARN]  {w}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse XSD to schema-model.json")
    ap.add_argument("--input", required=True)
    ap.add_argument("--imports", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    try:
        model = build_model(args.input, args.imports)
    except ValueError as e:
        sys.exit(f"[ERROR] {e}")
    write_outputs(model, args.out)


if __name__ == "__main__":
    main()
