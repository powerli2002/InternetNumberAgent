from __future__ import annotations

from agent.scripts.evaluate_rfc_rag import _find_expected_rank
from agent.scripts.sync_rfc_docs import (
    RFCSyncTarget,
    _convert_rfc_body_to_markdown,
    _extract_rfc_body,
    _render_rfc_markdown,
)
from agent.tools.rag_tool import DocumentChunk


def test_extract_rfc_body_removes_page_headers_and_toc() -> None:
    raw_text = """RFC 4271                         BGP-4                      January 2006

Table of Contents

   1. Introduction ....................................................4

Rekhter, et al.             Standards Track                     [Page 1]
RFC 4271                         BGP-4                      January 2006

1.  Introduction

Body line.

Author Name                  Standards Track                     [Page 2]
"""

    body = _extract_rfc_body(raw_text)

    assert "Table of Contents" not in body
    assert "[Page 1]" not in body
    assert body.startswith("1.  Introduction")
    assert "Body line." in body


def test_convert_rfc_body_to_markdown_promotes_numbered_headings() -> None:
    body_text = """1.  Introduction

Intro paragraph.

1.1.  Message Types

More details.

Appendix A.  Examples

Security Considerations
"""

    markdown = _convert_rfc_body_to_markdown(body_text)

    assert "## 1. Introduction" in markdown
    assert "### 1.1. Message Types" in markdown
    assert "## Appendix A. Examples" in markdown
    assert "## Security Considerations" in markdown


def test_render_rfc_markdown_contains_metadata_and_tags() -> None:
    target = RFCSyncTarget(4271, "bgp", "bgp4", ("BGP-4", "边界网关协议"))
    metadata = {
        "title": "A Border Gateway Protocol 4 (BGP-4)",
        "abstract": "This document discusses BGP.",
        "authors": ["Y. Rekhter"],
        "status": "DRAFT STANDARD",
        "pub_status": "DRAFT STANDARD",
        "pub_date": "December 2005",
        "source": "Inter-Domain Routing",
        "format": ["ASCII", "HTML"],
        "doi": "10.17487/RFC4271",
        "updated_by": ["RFC7606"],
    }

    markdown = _render_rfc_markdown(target, metadata, "## 1. Introduction\n\nBody")

    assert markdown.startswith("# RFC4271 - A Border Gateway Protocol 4 (BGP-4)")
    assert "## 元数据" in markdown
    assert "关键标签: BGP-4, 边界网关协议" in markdown
    assert "## 摘要" in markdown
    assert "## 正文" in markdown


def test_find_expected_rank_matches_source_only() -> None:
    chunks = [
        DocumentChunk(
            text="# RFC4271 - title",
            source="knowledge/rfc/bgp/rfc4760_multiprotocol_extensions.md",
            metadata={},
        ),
        DocumentChunk(
            text="irrelevant",
            source="knowledge/rfc/bgp/rfc4271_bgp4.md",
            metadata={},
        ),
    ]

    assert _find_expected_rank(chunks, "RFC4271") == 2
    assert _find_expected_rank(chunks, "RFC3912") is None
