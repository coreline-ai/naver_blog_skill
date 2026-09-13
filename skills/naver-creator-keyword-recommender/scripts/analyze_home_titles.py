#!/usr/bin/env python3
"""Validate and aggregate a locally observed Naver Blog Home title snapshot.

This script does not access a browser or the network. It emits aggregate title
patterns only; source titles never appear in the output document.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


INPUT_SCHEMA = "naver-blog-home-snapshot/v1"
OUTPUT_SCHEMA = "naver-blog-home-pattern-pack/v1"

TOP_KEYS = {"schema", "captured_at", "source", "pages"}
SOURCE_KEYS = {"directory_no", "group_id", "page_start", "page_end"}
PAGE_KEYS = {"page", "status", "reason", "items"}
ITEM_KEYS = {"kind", "text", "list_position"}
STATUSES = {"complete", "partial", "unavailable", "manual_partial"}

PATTERN_RULES = {
    "number": re.compile(r"\d"),
    "direct_quote": re.compile(r"[\"'“”‘’]"),
    "question": re.compile(r"\?|왜|어떻게|무엇|뭐가|뭐길래|가능한가|일까|인가"),
    "comparison": re.compile(r"비교|차이|공통점|달라졌|\bvs\.?\b", re.IGNORECASE),
    "howto_review": re.compile(r"방법|만들기|신청|정리|확인|조언|후기|리뷰|추천"),
    "problem_solution": re.compile(r"문제|해결|원인|대처|예방|고치는|줄이는|피하는|잡는"),
    "time_bound": re.compile(r"오늘|이번\s*주|이번\s*달|\d{4}년|\d{1,2}월|\d+일|\d+개월|\d+년\s*만"),
    "diary": re.compile(r"일상|일기|기록|월간|주간|하루"),
    "brackets": re.compile(r"[\[\]()（）]"),
    "exclamation": re.compile(r"!"),
}

SENSITIVITY_RULES = {
    "sensational": re.compile(r"초비상|충격|박살|대박|난리|폭발|품절|털린다|통곡|완벽|공포"),
    "personal_reputation": re.compile(r"악플|루머|불륜|열애|이혼|폭로|사생활|시어머니|며느리|논란"),
    "financial": re.compile(r"주가|주식|투자|실적|계약|매출|시총|대출|계좌|재산세|부동산|ISA|\d+\s*억|\d+\s*만원"),
    "medical": re.compile(r"질병|암|약물|치료|수술|감량|다이어트|건강|의사|병원"),
    "legal_crime": re.compile(r"수사|재판|고소|고발|범죄|징역|구속|처벌|무효|해킹"),
    "political": re.compile(r"대통령|국회의원|정당|선거|정부|여당|야당|정치"),
}


class ContractError(ValueError):
    """Raised when a snapshot violates the closed input contract."""


def exact_keys(obj: dict[str, Any], allowed: set[str], required: set[str], path: str) -> None:
    unknown = sorted(set(obj) - allowed)
    missing = sorted(required - set(obj))
    if unknown:
        raise ContractError(f"{path} contains unknown fields: {', '.join(unknown)}")
    if missing:
        raise ContractError(f"{path} is missing fields: {', '.join(missing)}")


def nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{path} must be a non-empty string")
    return value.strip()


def integer(value: Any, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{path} must be an integer >= {minimum}")
    return value


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    return re.sub(r"\s+", " ", normalized)


def captured_at_string(value: Any, path: str) -> str:
    captured_at = nonempty_string(value, path)
    try:
        datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{path} must be an ISO 8601 date-time") from exc
    return captured_at


def validate_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ContractError("document must be an object")
    exact_keys(document, TOP_KEYS, TOP_KEYS, "document")
    if document["schema"] != INPUT_SCHEMA:
        raise ContractError(f"document.schema must be {INPUT_SCHEMA!r}")

    captured_at = captured_at_string(document["captured_at"], "document.captured_at")
    source = document["source"]
    if not isinstance(source, dict):
        raise ContractError("document.source must be an object")
    exact_keys(source, SOURCE_KEYS, SOURCE_KEYS, "document.source")
    directory_no = integer(source["directory_no"], "document.source.directory_no")
    group_id = integer(source["group_id"], "document.source.group_id")
    page_start = integer(source["page_start"], "document.source.page_start", 1)
    page_end = integer(source["page_end"], "document.source.page_end", 1)
    if page_end < page_start:
        raise ContractError("document.source.page_end must be >= page_start")
    if page_end - page_start + 1 > 50:
        raise ContractError("document.source page range must not exceed 50 pages")

    raw_pages = document["pages"]
    if not isinstance(raw_pages, list):
        raise ContractError("document.pages must be an array")

    seen_pages: set[int] = set()
    pages: list[dict[str, Any]] = []
    for page_index, raw_page in enumerate(raw_pages):
        path = f"document.pages[{page_index}]"
        if not isinstance(raw_page, dict):
            raise ContractError(f"{path} must be an object")
        exact_keys(raw_page, PAGE_KEYS, {"page", "status", "items"}, path)
        page_number = integer(raw_page["page"], f"{path}.page", 1)
        if not page_start <= page_number <= page_end:
            raise ContractError(f"{path}.page is outside the requested page range")
        if page_number in seen_pages:
            raise ContractError(f"duplicate page: {page_number}")
        seen_pages.add(page_number)

        status = nonempty_string(raw_page["status"], f"{path}.status")
        if status not in STATUSES:
            raise ContractError(f"{path}.status is unsupported: {status!r}")
        reason = raw_page.get("reason")
        if reason is not None:
            reason = nonempty_string(reason, f"{path}.reason")

        raw_items = raw_page["items"]
        if not isinstance(raw_items, list):
            raise ContractError(f"{path}.items must be an array")
        if status == "unavailable" and raw_items:
            raise ContractError(f"{path}.items must be empty when status is unavailable")
        if status == "complete" and not raw_items:
            raise ContractError(f"{path}.items must not be empty when status is complete")

        seen_positions: set[int] = set()
        items: list[dict[str, Any]] = []
        for item_index, raw_item in enumerate(raw_items):
            item_path = f"{path}.items[{item_index}]"
            if not isinstance(raw_item, dict):
                raise ContractError(f"{item_path} must be an object")
            exact_keys(raw_item, ITEM_KEYS, ITEM_KEYS, item_path)
            if raw_item["kind"] != "home_title":
                raise ContractError(f"{item_path}.kind must be 'home_title'")
            text = nonempty_string(raw_item["text"], f"{item_path}.text")
            position = integer(raw_item["list_position"], f"{item_path}.list_position", 1)
            if position in seen_positions:
                raise ContractError(f"duplicate list_position {position} on page {page_number}")
            seen_positions.add(position)
            items.append({"kind": "home_title", "text": text, "list_position": position})

        pages.append(
            {
                "page": page_number,
                "status": status,
                "reason": reason,
                "items": sorted(items, key=lambda item: item["list_position"]),
            }
        )

    return {
        "captured_at": captured_at,
        "source": {
            "directory_no": directory_no,
            "group_id": group_id,
            "page_start": page_start,
            "page_end": page_end,
        },
        "pages": sorted(pages, key=lambda page: page["page"]),
    }


def aggregate(document: dict[str, Any]) -> dict[str, Any]:
    validated = validate_document(document)
    source = validated["source"]
    requested_pages = set(range(source["page_start"], source["page_end"] + 1))
    pages = validated["pages"]
    present_pages = {page["page"] for page in pages}
    missing_pages = sorted(requested_pages - present_pages)

    status_counts = Counter(page["status"] for page in pages)
    observed_titles = [item["text"] for page in pages for item in page["items"]]
    unique_titles: dict[str, str] = {}
    for title in observed_titles:
        unique_titles.setdefault(normalize_text(title), title)

    pattern_counts: Counter[str] = Counter()
    sensitivity_counts: Counter[str] = Counter()
    for title in unique_titles.values():
        normalized = unicodedata.normalize("NFKC", title)
        pattern_counts.update(name for name, rule in PATTERN_RULES.items() if rule.search(normalized))
        sensitivity_counts.update(
            name for name, rule in SENSITIVITY_RULES.items() if rule.search(normalized)
        )

    unique_count = len(unique_titles)
    lengths = [len(title) for title in unique_titles.values()]
    length_summary = {
        "average": round(sum(lengths) / len(lengths), 1) if lengths else 0.0,
        "minimum": min(lengths) if lengths else 0,
        "maximum": max(lengths) if lengths else 0,
    }

    all_complete = (
        not missing_pages
        and len(pages) == len(requested_pages)
        and all(page["status"] == "complete" for page in pages)
    )
    if not observed_titles:
        analysis_status = "unavailable"
    elif all_complete:
        analysis_status = "complete"
    else:
        analysis_status = "partial"

    limitations = [
        "snapshot_is_not_search_demand_or_click_through_rate",
        "blog_home_feed_may_be_personalized_and_change_over_time",
    ]
    if missing_pages:
        limitations.append("one_or_more_requested_pages_missing")
    if any(page["status"] != "complete" for page in pages):
        limitations.append("one_or_more_pages_incomplete")
    if len(observed_titles) != unique_count:
        limitations.append("duplicate_titles_removed_from_pattern_denominator")
    if any(page["status"] == "manual_partial" for page in pages):
        limitations.append("manual_partial_input")

    def summaries(counter: Counter[str]) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "count": count,
                "share": round(count / unique_count, 4) if unique_count else 0.0,
            }
            for name, count in sorted(counter.items(), key=lambda pair: (-pair[1], pair[0]))
        ]

    return {
        "schema": OUTPUT_SCHEMA,
        "captured_at": validated["captured_at"],
        "analysis_status": analysis_status,
        "coverage": {
            "requested_pages": len(requested_pages),
            "observed_pages": len(pages),
            "complete_pages": status_counts["complete"],
            "partial_pages": status_counts["partial"] + status_counts["manual_partial"],
            "unavailable_pages": status_counts["unavailable"],
            "missing_pages": missing_pages,
        },
        "titles_observed": len(observed_titles),
        "titles_unique": unique_count,
        "pattern_denominator": "unique_titles",
        "length": length_summary,
        "patterns": summaries(pattern_counts),
        "sensitivity_flags": summaries(sensitivity_counts),
        "limitations": limitations,
    }


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except FileNotFoundError as exc:
        raise ContractError(f"input file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"input is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ContractError("input JSON root must be an object")
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="naver-blog-home-snapshot/v1 JSON")
    parser.add_argument("--output", type=Path, help="write pattern pack JSON; stdout when omitted")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = aggregate(load_json(args.input))
    except ContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        sys.stdout.write(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
