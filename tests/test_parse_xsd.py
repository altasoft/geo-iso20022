import sys, os, json
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'parser'))

import pytest
import tempfile
from parse_xsd import build_model, write_outputs

SAMPLE_XSD = Path(__file__).parent.parent / "samples" / "sample_mini.xsd"


def test_build_model_has_required_keys():
    model = build_model(str(SAMPLE_XSD))
    assert "metadata" in model
    assert "nodesFlat" in model
    assert "tree" in model


def test_build_model_metadata():
    model = build_model(str(SAMPLE_XSD))
    meta = model["metadata"]
    assert meta["rootElement"] == "Document"
    assert "generatedAt" in meta
    assert isinstance(meta["warnings"], list)


def test_build_model_root_node_is_document():
    model = build_model(str(SAMPLE_XSD))
    root = next(n for n in model["nodesFlat"] if n["parentId"] is None)
    assert root["xmlTag"] == "Document"
    assert root["nodeKind"] == "root"
    assert root["xmlPath"] == "/Document"


def test_build_model_flat_has_no_children_key():
    """nodesFlat entries must not carry the inline children array."""
    model = build_model(str(SAMPLE_XSD))
    for node in model["nodesFlat"]:
        assert "children" not in node, f"Flat node {node['xmlPath']} has children key"


def test_build_model_tree_has_children_key():
    model = build_model(str(SAMPLE_XSD))
    assert "children" in model["tree"]


def test_write_outputs_creates_json_and_js(tmp_path):
    model = build_model(str(SAMPLE_XSD))
    out_json = tmp_path / "schema-model.json"
    write_outputs(model, str(out_json))
    assert out_json.exists()
    js_path = out_json.with_suffix(".js")
    assert js_path.exists()
    js_text = js_path.read_text(encoding="utf-8")
    assert js_text.startswith("window.__SCHEMA_MODEL__")


def test_build_model_codeSet_has_enumerations():
    model = build_model(str(SAMPLE_XSD))
    code_nodes = [n for n in model["nodesFlat"] if n["nodeKind"] == "codeSet"]
    assert len(code_nodes) >= 1
    for n in code_nodes:
        assert len(n["enumerations"]) > 0


def test_build_model_attribute_nodes_present():
    model = build_model(str(SAMPLE_XSD))
    attr_nodes = [n for n in model["nodesFlat"] if n["nodeKind"] == "attribute"]
    assert len(attr_nodes) >= 1
    assert any(n["xmlTag"] == "@Ccy" for n in attr_nodes)


def test_extract_message_name_from_filename():
    from parse_xsd import extract_message_name
    assert extract_message_name("GEO_pain.001.001.09.revision_0.2.xsd") == "pain.001.001.09"
    assert extract_message_name("pacs.008.001.08.xsd") == "pacs.008.001.08"


def test_build_model_raises_for_schema_with_no_root_element(tmp_path):
    """Schema with only type definitions and no xs:element raises ValueError."""
    xsd = tmp_path / "no_root.xsd"
    xsd.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:complexType name="OnlyType">
    <xs:sequence>
      <xs:element name="Field" type="xs:string"/>
    </xs:sequence>
  </xs:complexType>
</xs:schema>""", encoding="utf-8")
    with pytest.raises(ValueError, match="No top-level xs:element"):
        build_model(str(xsd))


def test_write_outputs_warning_path_resolves(tmp_path):
    """imports_dir with an unresolvable schemaLocation adds a warning, no crash."""
    xsd = tmp_path / "w.xsd"
    xsd.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:import schemaLocation="missing.xsd"/>
  <xs:element name="Document" type="xs:string"/>
</xs:schema>""", encoding="utf-8")
    model = build_model(str(xsd), imports_dir=str(tmp_path))
    assert any("Cannot resolve" in w for w in model["metadata"]["warnings"])
