import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'parser'))

import pytest
from conftest import parse_xsd
from schema_model import TypeRegistry, NodeBuilder, stable_id


# ── TypeRegistry ──────────────────────────────────────────────────────────────

def test_simple_type_restriction_facets():
    root = parse_xsd("""
        <xs:simpleType name="Max35Text">
          <xs:restriction base="xs:string">
            <xs:minLength value="1"/>
            <xs:maxLength value="35"/>
          </xs:restriction>
        </xs:simpleType>
    """)
    warnings = []
    reg = TypeRegistry(warnings)
    reg.load_tree(root)
    t = reg.get("Max35Text")
    assert t is not None
    assert t.base_type == "string"
    assert t.restrictions["minLength"] == "1"
    assert t.restrictions["maxLength"] == "35"
    assert warnings == []


def test_simple_type_enumerations():
    root = parse_xsd("""
        <xs:simpleType name="PayCode">
          <xs:restriction base="xs:string">
            <xs:enumeration value="CRED"/>
            <xs:enumeration value="DEBT"/>
          </xs:restriction>
        </xs:simpleType>
    """)
    warnings = []
    reg = TypeRegistry(warnings)
    reg.load_tree(root)
    t = reg.get("PayCode")
    assert t.enumerations == ["CRED", "DEBT"]


def test_complex_type_sequence_children():
    root = parse_xsd("""
        <xs:complexType name="Header">
          <xs:sequence>
            <xs:element name="MsgId" type="xs:string"/>
            <xs:element name="NbOfTxs" type="xs:string" minOccurs="0" maxOccurs="1"/>
          </xs:sequence>
        </xs:complexType>
    """)
    warnings = []
    reg = TypeRegistry(warnings)
    reg.load_tree(root)
    t = reg.get("Header")
    assert t is not None
    assert not t.is_choice
    assert len(t.children) == 2
    assert t.children[0].tag == "MsgId"
    assert t.children[1].min_occurs == 0
    assert t.children[1].max_occurs == "1"


def test_complex_type_choice():
    root = parse_xsd("""
        <xs:complexType name="PurpChoice">
          <xs:choice>
            <xs:element name="Cd" type="xs:string"/>
            <xs:element name="Prtry" type="xs:string"/>
          </xs:choice>
        </xs:complexType>
    """)
    warnings = []
    reg = TypeRegistry(warnings)
    reg.load_tree(root)
    t = reg.get("PurpChoice")
    assert t.is_choice is True
    assert len(t.children) == 2


def test_simple_content_attribute():
    root = parse_xsd("""
        <xs:complexType name="Amount">
          <xs:simpleContent>
            <xs:extension base="xs:decimal">
              <xs:attribute name="Ccy" type="xs:string" use="required"/>
            </xs:extension>
          </xs:simpleContent>
        </xs:complexType>
    """)
    warnings = []
    reg = TypeRegistry(warnings)
    reg.load_tree(root)
    t = reg.get("Amount")
    assert t.base_type == "decimal"
    assert len(t.attributes) == 1
    assert t.attributes[0].name == "Ccy"
    assert t.attributes[0].use == "required"


def test_documentation_extracted():
    root = parse_xsd("""
        <xs:complexType name="Header">
          <xs:annotation>
            <xs:documentation>Contains the message header.</xs:documentation>
          </xs:annotation>
          <xs:sequence>
            <xs:element name="Id" type="xs:string"/>
          </xs:sequence>
        </xs:complexType>
    """)
    warnings = []
    reg = TypeRegistry(warnings)
    reg.load_tree(root)
    t = reg.get("Header")
    assert t.documentation == "Contains the message header."


def test_unresolved_type_adds_warning():
    root = parse_xsd("""
        <xs:complexType name="Foo">
          <xs:sequence>
            <xs:element name="Bar" type="NonExistentType"/>
          </xs:sequence>
        </xs:complexType>
    """)
    warnings = []
    reg = TypeRegistry(warnings)
    reg.load_tree(root)
    reg.get("NonExistentType")
    assert any("NonExistentType" in w for w in warnings)


# ── NodeBuilder ───────────────────────────────────────────────────────────────

def _make_registry(fragment: str):
    root = parse_xsd(fragment)
    warnings = []
    reg = TypeRegistry(warnings)
    reg.load_tree(root)
    return reg, warnings


def test_root_node_path_and_kind():
    reg, warnings = _make_registry("""
        <xs:complexType name="Document">
          <xs:sequence>
            <xs:element name="Hdr" type="xs:string"/>
          </xs:sequence>
        </xs:complexType>
    """)
    builder = NodeBuilder(reg, warnings)
    tree = builder.build("Document", "Document")
    assert tree["xmlPath"] == "/Document"
    assert tree["nodeKind"] == "root"
    assert tree["isMandatory"] is True


def test_nested_element_xmlpath():
    reg, warnings = _make_registry("""
        <xs:complexType name="Document">
          <xs:sequence>
            <xs:element name="Hdr" type="Header"/>
          </xs:sequence>
        </xs:complexType>
        <xs:complexType name="Header">
          <xs:sequence>
            <xs:element name="Id" type="xs:string"/>
          </xs:sequence>
        </xs:complexType>
    """)
    builder = NodeBuilder(reg, warnings)
    builder.build("Document", "Document")
    paths = [n["xmlPath"] for n in builder.nodes_flat]
    assert "/Document/Hdr" in paths
    assert "/Document/Hdr/Id" in paths


def test_attribute_becomes_child_with_at_prefix():
    reg, warnings = _make_registry("""
        <xs:complexType name="Amt">
          <xs:simpleContent>
            <xs:extension base="xs:decimal">
              <xs:attribute name="Ccy" type="xs:string" use="required"/>
            </xs:extension>
          </xs:simpleContent>
        </xs:complexType>
        <xs:complexType name="Document">
          <xs:sequence>
            <xs:element name="Amt" type="Amt"/>
          </xs:sequence>
        </xs:complexType>
    """)
    builder = NodeBuilder(reg, warnings)
    builder.build("Document", "Document")
    paths = [n["xmlPath"] for n in builder.nodes_flat]
    assert "/Document/Amt/@Ccy" in paths
    attr_node = next(n for n in builder.nodes_flat if n["xmlPath"] == "/Document/Amt/@Ccy")
    assert attr_node["nodeKind"] == "attribute"
    assert attr_node["xmlTag"] == "@Ccy"


def test_cycle_detection_inserts_sentinel():
    reg, warnings = _make_registry("""
        <xs:complexType name="Document">
          <xs:sequence>
            <xs:element name="Node" type="LinkedNode"/>
          </xs:sequence>
        </xs:complexType>
        <xs:complexType name="LinkedNode">
          <xs:sequence>
            <xs:element name="Val" type="xs:string"/>
            <xs:element name="Next" type="LinkedNode" minOccurs="0"/>
          </xs:sequence>
        </xs:complexType>
    """)
    builder = NodeBuilder(reg, warnings)
    builder.build("Document", "Document")
    kinds = [n["nodeKind"] for n in builder.nodes_flat]
    assert "circularRef" in kinds


def test_multiplicity_formatted_correctly():
    reg, warnings = _make_registry("""
        <xs:complexType name="Document">
          <xs:sequence>
            <xs:element name="Item" type="xs:string"
                        minOccurs="0" maxOccurs="unbounded"/>
          </xs:sequence>
        </xs:complexType>
    """)
    builder = NodeBuilder(reg, warnings)
    builder.build("Document", "Document")
    item = next(n for n in builder.nodes_flat if n["xmlTag"] == "Item")
    assert item["multiplicity"] == "[0..∞]"
    assert item["isRepeating"] is True
    assert item["isMandatory"] is False


def test_node_kind_codeSet():
    reg, warnings = _make_registry("""
        <xs:simpleType name="PayCode">
          <xs:restriction base="xs:string">
            <xs:enumeration value="CRED"/>
            <xs:enumeration value="DEBT"/>
          </xs:restriction>
        </xs:simpleType>
        <xs:complexType name="Document">
          <xs:sequence>
            <xs:element name="Cd" type="PayCode"/>
          </xs:sequence>
        </xs:complexType>
    """)
    builder = NodeBuilder(reg, warnings)
    builder.build("Document", "Document")
    cd = next(n for n in builder.nodes_flat if n["xmlTag"] == "Cd")
    assert cd["nodeKind"] == "codeSet"
    assert cd["enumerations"] == ["CRED", "DEBT"]


def test_node_kind_amount_by_name():
    reg, warnings = _make_registry("""
        <xs:complexType name="ActiveOrHistoricCurrencyAndAmount">
          <xs:simpleContent>
            <xs:extension base="xs:decimal">
              <xs:attribute name="Ccy" type="xs:string" use="required"/>
            </xs:extension>
          </xs:simpleContent>
        </xs:complexType>
        <xs:complexType name="Document">
          <xs:sequence>
            <xs:element name="Amt" type="ActiveOrHistoricCurrencyAndAmount"/>
          </xs:sequence>
        </xs:complexType>
    """)
    builder = NodeBuilder(reg, warnings)
    builder.build("Document", "Document")
    amt = next(n for n in builder.nodes_flat if n["xmlTag"] == "Amt")
    assert amt["nodeKind"] == "amount"


def test_stable_id_is_deterministic():
    id1 = stable_id("/Document/Hdr", "Header")
    id2 = stable_id("/Document/Hdr", "Header")
    id3 = stable_id("/Document/Hdr", "OtherType")
    assert id1 == id2
    assert id1 != id3
    assert len(id1) == 16


# ── Georgian (KA) documentation ───────────────────────────────────────────────

def test_get_doc_returns_en_definition_by_default():
    root = parse_xsd("""
        <xs:complexType name="Header">
          <xs:annotation>
            <xs:documentation source="Name">GroupHeader</xs:documentation>
            <xs:documentation source="Definition" xml:lang="EN">English definition.</xs:documentation>
            <xs:documentation source="Definition" xml:lang="KA">Georgian definition.</xs:documentation>
          </xs:annotation>
          <xs:sequence>
            <xs:element name="Id" type="xs:string"/>
          </xs:sequence>
        </xs:complexType>
    """)
    warnings = []
    reg = TypeRegistry(warnings)
    reg.load_tree(root)
    t = reg.get("Header")
    assert t.documentation == "English definition."
    assert t.documentation_ka == "Georgian definition."


def test_get_doc_ka_only_when_lang_specified():
    root = parse_xsd("""
        <xs:complexType name="Header">
          <xs:annotation>
            <xs:documentation source="Definition" xml:lang="EN">EN text.</xs:documentation>
            <xs:documentation source="Definition" xml:lang="KA">KA text.</xs:documentation>
          </xs:annotation>
          <xs:sequence>
            <xs:element name="Id" type="xs:string"/>
          </xs:sequence>
        </xs:complexType>
    """)
    warnings = []
    reg = TypeRegistry(warnings)
    reg.load_tree(root)
    t = reg.get("Header")
    assert t.documentation == "EN text."
    assert t.documentation_ka == "KA text."


def test_get_doc_ka_returns_none_when_no_ka_annotation():
    root = parse_xsd("""
        <xs:complexType name="Header">
          <xs:annotation>
            <xs:documentation source="Definition" xml:lang="EN">Only English.</xs:documentation>
          </xs:annotation>
          <xs:sequence>
            <xs:element name="Id" type="xs:string"/>
          </xs:sequence>
        </xs:complexType>
    """)
    warnings = []
    reg = TypeRegistry(warnings)
    reg.load_tree(root)
    t = reg.get("Header")
    assert t.documentation == "Only English."
    assert t.documentation_ka is None


def test_documentation_ka_propagated_to_node():
    reg, warnings = _make_registry("""
        <xs:complexType name="Document">
          <xs:sequence>
            <xs:element name="Hdr" type="Header">
              <xs:annotation>
                <xs:documentation source="Definition" xml:lang="EN">Header EN.</xs:documentation>
                <xs:documentation source="Definition" xml:lang="KA">Header KA.</xs:documentation>
              </xs:annotation>
            </xs:element>
          </xs:sequence>
        </xs:complexType>
        <xs:complexType name="Header">
          <xs:sequence>
            <xs:element name="Id" type="xs:string"/>
          </xs:sequence>
        </xs:complexType>
    """)
    builder = NodeBuilder(reg, warnings)
    builder.build("Document", "Document")
    hdr = next(n for n in builder.nodes_flat if n["xmlTag"] == "Hdr")
    assert hdr["documentation"] == "Header EN."
    assert hdr["documentationKA"] == "Header KA."


def test_documentation_ka_falls_back_to_type_annotation():
    reg, warnings = _make_registry("""
        <xs:complexType name="Document">
          <xs:sequence>
            <xs:element name="Hdr" type="Header"/>
          </xs:sequence>
        </xs:complexType>
        <xs:complexType name="Header">
          <xs:annotation>
            <xs:documentation source="Definition" xml:lang="EN">Type EN.</xs:documentation>
            <xs:documentation source="Definition" xml:lang="KA">Type KA.</xs:documentation>
          </xs:annotation>
          <xs:sequence>
            <xs:element name="Id" type="xs:string"/>
          </xs:sequence>
        </xs:complexType>
    """)
    builder = NodeBuilder(reg, warnings)
    builder.build("Document", "Document")
    hdr = next(n for n in builder.nodes_flat if n["xmlTag"] == "Hdr")
    assert hdr["documentation"] == "Type EN."
    assert hdr["documentationKA"] == "Type KA."
