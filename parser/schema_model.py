"""
schema_model.py
Two-pass XSD model builder.
  Pass 1 — TypeRegistry: collects all type/element definitions
  Pass 2 — NodeBuilder:  expands element tree with path-keyed cycle detection
"""
import hashlib
from lxml import etree

XS = "http://www.w3.org/2001/XMLSchema"


def _xs(tag: str) -> str:
    return f"{{{XS}}}{tag}"


def stable_id(xml_path: str, type_name: str) -> str:
    raw = f"{xml_path}|{type_name}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _strip_ns(qname: str | None) -> str | None:
    """Remove namespace prefix: 'xs:string' → 'string'."""
    if qname is None:
        return None
    return qname.split(":")[-1] if ":" in qname else qname


def _format_max(value: str) -> str:
    return "∞" if value == "unbounded" else value


def _format_multiplicity(min_occurs: int, max_occurs: str) -> str:
    return f"[{min_occurs}..{_format_max(max_occurs)}]"


def _detect_node_kind(type_name: str, base_type: str, has_enums: bool,
                      has_children: bool, is_choice_child: bool,
                      is_attribute: bool) -> str:
    if is_attribute:
        return "attribute"
    if has_enums:
        return "codeSet"
    lname = (type_name or "").lower()
    lbase = (base_type or "").lower()
    if "amount" in lname:
        return "amount"
    if "date" in lname or lbase in ("date", "datetime"):
        return "date"
    if lbase == "boolean":
        return "boolean"
    if has_children:
        return "complexType"
    if lbase == "decimal":
        return "amount"
    if lbase in ("string", "normalizedstring", "token"):
        return "text"
    if is_choice_child:
        return "choice"
    return "simpleType"


# ── TypeInfo / ChildDef / AttributeDef ───────────────────────────────────────

class ChildDef:
    __slots__ = ("tag", "type_name", "min_occurs", "max_occurs", "documentation", "label")

    def __init__(self, tag: str, type_name: str | None,
                 min_occurs: int = 1, max_occurs: str = "1",
                 documentation: str | None = None,
                 label: str | None = None):
        self.tag = tag
        self.type_name = type_name
        self.min_occurs = min_occurs
        self.max_occurs = max_occurs
        self.documentation = documentation
        self.label = label


class AttributeDef:
    __slots__ = ("name", "type_name", "use")

    def __init__(self, name: str, type_name: str | None, use: str = "optional"):
        self.name = name
        self.type_name = type_name
        self.use = use


class TypeInfo:
    def __init__(self):
        self.kind: str = "unknown"
        self.base_type: str | None = None
        self.children: list[ChildDef] = []
        self.is_choice: bool = False
        self.enumerations: list[str] = []
        self.restrictions: dict = {
            "pattern": None, "minLength": None, "maxLength": None,
            "length": None, "totalDigits": None, "fractionDigits": None,
            "minInclusive": None,
        }
        self.documentation: str | None = None
        self.attributes: list[AttributeDef] = []


# ── Built-in XSD primitive type names (after namespace stripping) ─────────────

_BUILTIN_XSD_TYPES: frozenset[str] = frozenset({
    "string", "normalizedString", "token", "boolean",
    "decimal", "float", "double", "integer",
    "positiveInteger", "nonNegativeInteger", "negativeInteger", "long",
    "int", "short", "byte", "unsignedLong", "unsignedInt",
    "unsignedShort", "unsignedByte",
    "date", "dateTime", "time", "gYear", "gYearMonth", "gMonth",
    "gMonthDay", "gDay", "duration",
    "anyURI", "base64Binary", "hexBinary", "QName", "NOTATION", "anyType",
})


# ── TypeRegistry — pass 1 ─────────────────────────────────────────────────────

class TypeRegistry:
    def __init__(self, warnings: list):
        self._types: dict[str, TypeInfo] = {}
        self._warnings = warnings

    def load_tree(self, schema_el) -> None:
        for child in schema_el:
            if child.tag == etree.Comment:
                continue
            local = etree.QName(child.tag).localname
            name = child.get("name")
            if not name:
                continue
            if local == "complexType":
                self._types[name] = self._parse_complex(child)
            elif local == "simpleType":
                self._types[name] = self._parse_simple(child)

    def get(self, type_name: str) -> TypeInfo | None:
        info = self._types.get(type_name)
        if info is None and type_name and type_name not in _BUILTIN_XSD_TYPES:
            self._warnings.append(f"Unresolved type reference: {type_name!r}")
        return info

    def _parse_complex(self, el) -> TypeInfo:
        info = TypeInfo()
        info.kind = "complexType"
        info.documentation = self._get_doc(el)

        seq = el.find(_xs("sequence"))
        cho = el.find(_xs("choice"))
        sc  = el.find(_xs("simpleContent"))

        if seq is not None:
            info.children = self._parse_container(seq)
        elif cho is not None:
            info.is_choice = True
            info.children = self._parse_container(cho)
        elif sc is not None:
            ext = sc.find(_xs("extension"))
            if ext is not None:
                info.base_type = _strip_ns(ext.get("base"))
                for a in ext.findall(_xs("attribute")):
                    info.attributes.append(self._parse_attr(a))

        for a in el.findall(_xs("attribute")):
            info.attributes.append(self._parse_attr(a))
        return info

    def _parse_simple(self, el) -> TypeInfo:
        info = TypeInfo()
        info.kind = "simpleType"
        info.documentation = self._get_doc(el)
        restr = el.find(_xs("restriction"))
        if restr is not None:
            info.base_type = _strip_ns(restr.get("base"))
            for ev in restr.findall(_xs("enumeration")):
                info.enumerations.append(ev.get("value"))
            for facet in ("pattern", "minLength", "maxLength", "length",
                          "totalDigits", "fractionDigits", "minInclusive"):
                fel = restr.find(_xs(facet))
                if fel is not None:
                    info.restrictions[facet] = fel.get("value")
        return info

    def _parse_container(self, container) -> list[ChildDef]:
        children = []
        for child in container:
            if child.tag == etree.Comment:
                continue
            local = etree.QName(child.tag).localname
            if local == "element":
                children.append(ChildDef(
                    tag=child.get("name", ""),
                    type_name=_strip_ns(child.get("type")),
                    min_occurs=int(child.get("minOccurs", 1)),
                    max_occurs=child.get("maxOccurs", "1"),
                    documentation=self._get_doc(child),
                    label=self._get_label(child),
                ))
            elif local in ("sequence", "choice"):
                children.extend(self._parse_container(child))
        return children

    @staticmethod
    def _parse_attr(el) -> AttributeDef:
        return AttributeDef(
            name=el.get("name", ""),
            type_name=_strip_ns(el.get("type")),
            use=el.get("use", "optional"),
        )

    @staticmethod
    def _get_doc(el) -> str | None:
        ann = el.find(_xs("annotation"))
        if ann is None:
            return None
        docs = ann.findall(_xs("documentation"))
        if not docs:
            return None
        # ISO 20022 XSDs use two <xs:documentation> elements per annotation:
        #   source="Name"       — the ISO class name (e.g. "PaymentInformationIdentification")
        #   source="Definition" — the human-readable description (what we want here)
        # Prefer Definition; fall back to the last doc element, then the first.
        for doc in docs:
            if doc.get("source") == "Definition" and doc.text:
                return doc.text.strip()
        last = docs[-1]
        if last.text:
            return last.text.strip()
        return docs[0].text.strip() if docs[0].text else None

    @staticmethod
    def _get_label(el) -> str | None:
        """Return the source='Name' documentation text — the full ISO element name."""
        ann = el.find(_xs("annotation"))
        if ann is None:
            return None
        for doc in ann.findall(_xs("documentation")):
            if doc.get("source") == "Name" and doc.text:
                return doc.text.strip()
        return None


# ── NodeBuilder — pass 2 ──────────────────────────────────────────────────────

class NodeBuilder:
    def __init__(self, registry: TypeRegistry, warnings: list):
        self._reg = registry
        self._warnings = warnings
        self.nodes_flat: list[dict] = []

    def build(self, root_tag: str, root_type: str) -> dict:
        return self._expand(
            xml_tag=root_tag,
            type_name=root_type,
            xml_path=f"/{root_tag}",
            parent_id=None,
            min_occurs=1,
            max_occurs="1",
            is_choice_child=False,
            is_attribute=False,
            ancestor_paths=frozenset(),
            ancestor_types=frozenset(),
            is_root=True,
        )

    def _expand(self, xml_tag: str, type_name: str | None, xml_path: str,
                parent_id: str | None, min_occurs: int, max_occurs: str,
                is_choice_child: bool, is_attribute: bool,
                ancestor_paths: frozenset, ancestor_types: frozenset,
                is_root: bool = False,
                elem_doc: str | None = None,
                elem_label: str | None = None) -> dict:

        # Detect cycles by type name (handles recursive types like linked lists)
        if type_name and type_name in ancestor_types:
            return self._sentinel(xml_tag, type_name, xml_path,
                                  parent_id, min_occurs, max_occurs)
        # Also detect cycles by xml_path (handles other structural cycles)
        if xml_path in ancestor_paths:
            return self._sentinel(xml_tag, type_name, xml_path,
                                  parent_id, min_occurs, max_occurs)

        info = self._reg.get(type_name) if type_name else None

        child_defs: list[ChildDef] = info.children if info else []
        attr_defs:  list[AttributeDef] = info.attributes if info else []
        base_type   = info.base_type if info else None
        enumerations = info.enumerations if info else []
        restrictions = dict(info.restrictions) if info else {
            k: None for k in ("pattern", "minLength", "maxLength", "length",
                               "totalDigits", "fractionDigits", "minInclusive")
        }
        # Element-level annotation takes priority over type-level annotation.
        documentation = elem_doc or (info.documentation if info else None)
        is_choice = info.is_choice if info else False

        node_kind = "root" if is_root else _detect_node_kind(
            type_name=type_name or "",
            base_type=base_type or "",
            has_enums=bool(enumerations),
            has_children=bool(child_defs or attr_defs),
            is_choice_child=is_choice_child,
            is_attribute=is_attribute,
        )

        node_id = stable_id(xml_path, type_name or "")
        is_repeating = (max_occurs == "unbounded" or
                        (max_occurs.isdigit() and int(max_occurs) > 1))

        node: dict = {
            "id": node_id,
            "parentId": parent_id,
            "label": elem_label,   # ISO full name from source="Name" annotation, or None
            "name": xml_tag,
            "xmlTag": xml_tag,
            "xmlPath": xml_path,
            "typeName": type_name,
            "baseType": base_type,
            "nodeKind": node_kind,
            "minOccurs": min_occurs,
            "maxOccurs": max_occurs,
            "multiplicity": _format_multiplicity(min_occurs, max_occurs),
            "isMandatory": min_occurs >= 1,
            "isRepeating": is_repeating,
            "isChoice": is_choice,
            "documentation": documentation,
            "restrictions": restrictions,
            "enumerations": enumerations,
            "childrenIds": [],
            "children": [],
        }

        new_ancestors = ancestor_paths | {xml_path}
        new_ancestor_types = ancestor_types | ({type_name} if type_name else set())

        for cdef in child_defs:
            child_path = f"{xml_path}/{cdef.tag}"
            child = self._expand(
                xml_tag=cdef.tag,
                type_name=cdef.type_name,
                xml_path=child_path,
                parent_id=node_id,
                min_occurs=cdef.min_occurs,
                max_occurs=cdef.max_occurs,
                is_choice_child=is_choice,
                is_attribute=False,
                ancestor_paths=new_ancestors,
                ancestor_types=new_ancestor_types,
                elem_doc=cdef.documentation,
                elem_label=cdef.label,
            )
            node["childrenIds"].append(child["id"])
            node["children"].append(child)

        for adef in attr_defs:
            attr_path = f"{xml_path}/@{adef.name}"
            attr = self._expand(
                xml_tag=f"@{adef.name}",
                type_name=adef.type_name,
                xml_path=attr_path,
                parent_id=node_id,
                min_occurs=1 if adef.use == "required" else 0,
                max_occurs="1",
                is_choice_child=False,
                is_attribute=True,
                ancestor_paths=new_ancestors,
                ancestor_types=new_ancestor_types,
            )
            node["childrenIds"].append(attr["id"])
            node["children"].append(attr)

        self.nodes_flat.append(node)
        return node

    def _sentinel(self, xml_tag, type_name, xml_path, parent_id,
                  min_occurs, max_occurs) -> dict:
        node_id = stable_id(xml_path + ":circular", type_name or "")
        node = {
            "id": node_id, "parentId": parent_id,
            "label": None, "name": xml_tag, "xmlTag": xml_tag, "xmlPath": xml_path,
            "typeName": type_name, "baseType": None,
            "nodeKind": "circularRef",
            "minOccurs": min_occurs, "maxOccurs": max_occurs,
            "multiplicity": _format_multiplicity(min_occurs, max_occurs),
            "isMandatory": min_occurs >= 1, "isRepeating": False,
            "isChoice": False, "documentation": None,
            "restrictions": {k: None for k in ("pattern", "minLength", "maxLength",
                                                "length", "totalDigits", "fractionDigits",
                                                "minInclusive")},
            "enumerations": [], "childrenIds": [], "children": [],
        }
        self.nodes_flat.append(node)
        return node
