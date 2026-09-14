"""Deterministic visible-body metrics for naver-post/v1 documents."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


REFERENCE_HEADINGS = {
    "참고자료",
    "참고 자료",
    "참고문헌",
    "참고 문헌",
    "출처",
    "sources",
    "references",
}
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")


def normalize_visible_text(value: str) -> str:
    """Normalize Unicode and whitespace, and remove raw URLs from visible text."""
    text = unicodedata.normalize("NFKC", value)
    text = URL_RE.sub("", text)
    return WHITESPACE_RE.sub(" ", text).strip()


def _block_text(block: dict[str, Any]) -> list[str]:
    kind = block.get("type")
    if kind in {"paragraph", "heading"}:
        return [block.get("text", "")]
    if kind == "list":
        return [item.get("text", "") for item in block.get("items", []) if isinstance(item, dict)]
    if kind == "table":
        values = list(block.get("columns", []))
        values.extend(cell for row in block.get("rows", []) for cell in row)
        return values
    if kind == "callout":
        return [block.get("title", ""), block.get("text", "")]
    # Images, dividers, alt text, and captions do not count toward article depth.
    return []


def visible_body_text(
    post: dict[str, Any], *, excluded_block_ids: list[str] | tuple[str, ...] = ()
) -> str:
    """Return public body text while excluding explicitly identified metadata blocks."""
    excluded = set(excluded_block_ids)
    parts: list[str] = []
    in_reference_section = False
    for block in post.get("blocks", []):
        if not isinstance(block, dict):
            continue
        if block.get("id") in excluded:
            continue
        if block.get("type") == "heading":
            heading = normalize_visible_text(str(block.get("text", ""))).casefold()
            if heading in REFERENCE_HEADINGS:
                in_reference_section = True
                continue
            if in_reference_section:
                # A new non-reference heading resumes public instructional content.
                in_reference_section = False
        if in_reference_section:
            continue
        parts.extend(str(value) for value in _block_text(block))
    return normalize_visible_text(" ".join(parts))


def body_metrics(
    post: dict[str, Any], *, excluded_block_ids: list[str] | tuple[str, ...] = ()
) -> dict[str, Any]:
    unique_ids = list(dict.fromkeys(excluded_block_ids))
    text = visible_body_text(post, excluded_block_ids=unique_ids)
    return {
        "schema": "naver-content-metrics/v1",
        "body_char_count": len(text),
        "excluded_block_ids": unique_ids,
        "measurement": "NFKC Unicode code points after whitespace collapse; excludes H1, tags, references, URLs, images, alt and identified caption blocks",
    }
