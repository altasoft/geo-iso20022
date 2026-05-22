import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'parser'))

from diff_xsd import build_diff, match_nodes


def _node(xml_path, min_occurs=0, max_occurs="1", type_name="T",
          enumerations=None, documentation=None, is_mandatory=None,
          restrictions=None):
    mn = min_occurs
    return {
        "xmlPath": xml_path,
        "xmlTag": xml_path.split("/")[-1],
        "typeName": type_name,
        "minOccurs": mn,
        "maxOccurs": max_occurs,
        "multiplicity": f"[{mn}..{'∞' if max_occurs == 'unbounded' else max_occurs}]",
        "isMandatory": mn >= 1 if is_mandatory is None else is_mandatory,
        "isRepeating": max_occurs == "unbounded",
        "isChoice": False,
        "enumerations": enumerations or [],
        "documentation": documentation,
        "restrictions": restrictions or {k: None for k in (
            "pattern", "minLength", "maxLength", "length",
            "totalDigits", "fractionDigits", "minInclusive")},
    }


def _model(nodes):
    return {"metadata": {"sourceFile": "test"}, "nodesFlat": nodes}


def test_added_optional_node_is_nonbreaking():
    old = _model([_node("/Document")])
    new = _model([_node("/Document"), _node("/Document/NewField", min_occurs=0)])
    diff = build_diff(old, new)
    changes = [c for c in diff["changes"] if c["changeType"] == "AddedNode"]
    assert len(changes) == 1
    assert changes[0]["severity"] == "NonBreaking"


def test_added_mandatory_node_is_breaking():
    old = _model([_node("/Document")])
    new = _model([_node("/Document"), _node("/Document/NewField", min_occurs=1)])
    diff = build_diff(old, new)
    changes = [c for c in diff["changes"] if c["changeType"] == "AddedNode"]
    assert changes[0]["severity"] == "Breaking"


def test_removed_node_is_breaking():
    old = _model([_node("/Document"), _node("/Document/Field")])
    new = _model([_node("/Document")])
    diff = build_diff(old, new)
    changes = [c for c in diff["changes"] if c["changeType"] == "RemovedNode"]
    assert len(changes) == 1
    assert changes[0]["severity"] == "Breaking"
    assert changes[0]["xmlPath"] == "/Document/Field"


def test_max_occurs_reduced_is_breaking():
    old = _model([_node("/Document/Item", max_occurs="unbounded")])
    new = _model([_node("/Document/Item", max_occurs="1")])
    diff = build_diff(old, new)
    changes = [c for c in diff["changes"] if c["changeType"] == "MaxOccursChanged"]
    assert len(changes) == 1
    assert changes[0]["severity"] == "Breaking"


def test_max_occurs_increased_is_nonbreaking():
    old = _model([_node("/Document/Item", max_occurs="1")])
    new = _model([_node("/Document/Item", max_occurs="unbounded")])
    diff = build_diff(old, new)
    changes = [c for c in diff["changes"] if c["changeType"] == "MaxOccursChanged"]
    assert changes[0]["severity"] == "NonBreaking"


def test_enumeration_removed_is_breaking():
    old = _model([_node("/Document/Cd", enumerations=["A", "B", "C"])])
    new = _model([_node("/Document/Cd", enumerations=["A", "B"])])
    diff = build_diff(old, new)
    changes = [c for c in diff["changes"] if c["changeType"] == "EnumerationRemoved"]
    assert len(changes) == 1
    assert changes[0]["severity"] == "Breaking"
    assert changes[0]["oldValue"] == "C"


def test_enumeration_added_is_nonbreaking():
    old = _model([_node("/Document/Cd", enumerations=["A", "B"])])
    new = _model([_node("/Document/Cd", enumerations=["A", "B", "C"])])
    diff = build_diff(old, new)
    changes = [c for c in diff["changes"] if c["changeType"] == "EnumerationAdded"]
    assert changes[0]["severity"] == "NonBreaking"


def test_documentation_changed_is_informational():
    old = _model([_node("/Document/F", documentation="Old doc")])
    new = _model([_node("/Document/F", documentation="New doc")])
    diff = build_diff(old, new)
    changes = [c for c in diff["changes"] if c["changeType"] == "DocumentationChanged"]
    assert changes[0]["severity"] == "Informational"


def test_restriction_stricter_is_breaking():
    old_r = {"pattern": None, "minLength": None, "maxLength": "35",
             "length": None, "totalDigits": None, "fractionDigits": None, "minInclusive": None}
    new_r = {"pattern": None, "minLength": None, "maxLength": "10",
             "length": None, "totalDigits": None, "fractionDigits": None, "minInclusive": None}
    old = _model([_node("/Document/F", restrictions=old_r)])
    new = _model([_node("/Document/F", restrictions=new_r)])
    diff = build_diff(old, new)
    changes = [c for c in diff["changes"] if c["changeType"] == "RestrictionChanged"]
    assert len(changes) == 1
    assert changes[0]["severity"] == "Breaking"


def test_summary_counts_correct():
    old = _model([_node("/Document"), _node("/Document/A"), _node("/Document/B")])
    new = _model([_node("/Document"), _node("/Document/A", max_occurs="unbounded"),
                  _node("/Document/C", min_occurs=0)])
    diff = build_diff(old, new)
    s = diff["summary"]
    assert s["added"] == 1    # /Document/C added
    assert s["removed"] == 1  # /Document/B removed
    assert s["changed"] == 1  # /Document/A maxOccurs changed


def test_type_changed_is_breaking():
    old = _model([_node("/Document/F", type_name="OldType")])
    new = _model([_node("/Document/F", type_name="NewType")])
    diff = build_diff(old, new)
    changes = [c for c in diff["changes"] if c["changeType"] == "TypeChanged"]
    assert len(changes) == 1
    assert changes[0]["severity"] == "Breaking"


def test_min_occurs_increased_is_breaking():
    old = _model([_node("/Document/F", min_occurs=0)])
    new = _model([_node("/Document/F", min_occurs=1)])
    diff = build_diff(old, new)
    changes = [c for c in diff["changes"] if c["changeType"] == "MinOccursChanged"]
    assert len(changes) == 1
    assert changes[0]["severity"] == "Breaking"


def test_length_restriction_change_is_always_breaking():
    old_r = {"pattern": None, "minLength": None, "maxLength": None,
             "length": "10", "totalDigits": None, "fractionDigits": None, "minInclusive": None}
    new_r = {"pattern": None, "minLength": None, "maxLength": None,
             "length": "20", "totalDigits": None, "fractionDigits": None, "minInclusive": None}
    old = _model([_node("/Document/F", restrictions=old_r)])
    new = _model([_node("/Document/F", restrictions=new_r)])
    diff = build_diff(old, new)
    changes = [c for c in diff["changes"] if c["changeType"] == "RestrictionChanged"]
    assert len(changes) == 1
    assert changes[0]["severity"] == "Breaking"
