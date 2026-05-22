import textwrap
from lxml import etree


XS_NS = "http://www.w3.org/2001/XMLSchema"


def parse_xsd(fragment: str):
    """Wrap an XSD fragment in a schema element and return the root."""
    xml = textwrap.dedent(f"""
        <?xml version="1.0" encoding="UTF-8"?>
        <xs:schema xmlns:xs="{XS_NS}" targetNamespace="urn:test"
                   elementFormDefault="qualified">
          {fragment}
        </xs:schema>
    """).strip()
    return etree.fromstring(xml.encode())
