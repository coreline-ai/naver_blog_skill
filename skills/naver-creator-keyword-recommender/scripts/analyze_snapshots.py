#!/usr/bin/env python3
"""Validate and aggregate manually observed Naver Creator Advisor snapshots.

This script does not access the network or a browser. It converts a local
naver-creator-snapshots/v1 document into naver-creator-keyword-pack/v1.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable


INPUT_SCHEMA = "naver-creator-snapshots/v1"
OUTPUT_SCHEMA = "naver-creator-keyword-pack/v1"

SURFACE_KINDS = {
    "search_inflow": {"search_keyword"},
    "main_inflow": {"main_title"},
    "business": {"business_keyword", "business_title", "business_signal"},
    "manual": {
        "search_keyword",
        "main_title",
        "business_keyword",
        "business_title",
        "business_signal",
    },
}
KEYWORD_KINDS = {"search_keyword", "business_keyword"}
TITLE_KINDS = {"main_title", "business_title"}
STATUSES = {"complete", "partial", "unavailable", "manual_partial"}

TOP_KEYS = {"schema", "captured_at", "snapshots"}
SNAPSHOT_KEYS = {"date", "surface", "status", "reason", "items"}
ITEM_KEYS = {
    "kind",
    "text",
    "category",
    "segment",
    "list_position",
    "indicator_raw",
}

PATTERN_RULES = {
    "direct_quote": re.compile(r"[\"'“”‘’]"),
    "number": re.compile(r"\d"),
    "question": re.compile(r"\?|왜|어떻게|뭐길래|무엇|맞아|일까|인가"),
    "conflict": re.compile(r"논란|거절|무효|악플|사과|죄송|초비상|폭로|대란|파다하|충격"),
    "reversal": re.compile(r"반전|오히려|알고\s*보니|했는데|아닌데|잘한\s*거|달랐|뜻밖"),
    "information_gap": re.compile(r"이유|정체|지금은|뭐길래|무엇|왜|어떻게|결과|한\s*가지"),
}

SENSITIVITY_RULES = {
    "personal_reputation": re.compile(r"악플|루머|불륜|열애|이혼|폭로|사생활|시어머니|며느리|논란"),
    "financial": re.compile(r"주가|주식|투자|실적|계약|매출|시총|\d+\s*억|\d+\s*만원"),
    "medical": re.compile(r"질병|암|약물|치료|수술|감량|다이어트|건강|의사"),
    "legal_crime": re.compile(r"수사|재판|고소|고발|범죄|징역|구속|처벌|무효"),
    "political": re.compile(r"대통령|국회의원|정당|선거|정부|여당|야당|정치"),
}


class ContractError(ValueError):
    """Raised when the input does not satisfy the snapshot contract."""


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().lower()
    return re.sub(r"\s+", " ", value)


def parse_date(value: str, path: str) -> date:
    if not isinstance(value, str):
        raise ContractError(f"{path} must be a YYYY-MM-DD string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ContractError(f"{path} must be YYYY-MM-DD: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ContractError(f"{path} must be zero-padded YYYY-MM-DD: {value!r}")
    return parsed


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


def validate_document(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        raise ContractError("document must be an object")
    exact_keys(document, TOP_KEYS, TOP_KEYS, "document")
    if document["schema"] != INPUT_SCHEMA:
        raise ContractError(f"document.schema must be {INPUT_SCHEMA!r}")
    nonempty_string(document["captured_at"], "document.captured_at")
    snapshots = document["snapshots"]
    if not isinstance(snapshots, list):
        raise ContractError("document.snapshots must be an array")

    seen_snapshot_keys: set[tuple[str, str]] = set()
    validated: list[dict[str, Any]] = []
    for index, raw_snapshot in enumerate(snapshots):
        path = f"document.snapshots[{index}]"
        if not isinstance(raw_snapshot, dict):
            raise ContractError(f"{path} must be an object")
        exact_keys(raw_snapshot, SNAPSHOT_KEYS, {"date", "surface", "status", "items"}, path)
        snapshot_date = parse_date(raw_snapshot["date"], f"{path}.date")
        surface = nonempty_string(raw_snapshot["surface"], f"{path}.surface")
        if surface not in SURFACE_KINDS:
            raise ContractError(f"{path}.surface is unsupported: {surface!r}")
        status = nonempty_string(raw_snapshot["status"], f"{path}.status")
        if status not in STATUSES:
            raise ContractError(f"{path}.status is unsupported: {status!r}")
        reason = raw_snapshot.get("reason")
        if reason is not None:
            nonempty_string(reason, f"{path}.reason")
        items = raw_snapshot["items"]
        if not isinstance(items, list):
            raise ContractError(f"{path}.items must be an array")
        if status == "unavailable" and items:
            raise ContractError(f"{path}.items must be empty when status is unavailable")

        snapshot_key = (snapshot_date.isoformat(), surface)
        if snapshot_key in seen_snapshot_keys:
            raise ContractError(f"duplicate snapshot for date/surface: {snapshot_key}")
        seen_snapshot_keys.add(snapshot_key)

        validated_items: list[dict[str, Any]] = []
        for item_index, raw_item in enumerate(items):
            item_path = f"{path}.items[{item_index}]"
            if not isinstance(raw_item, dict):
                raise ContractError(f"{item_path} must be an object")
            exact_keys(raw_item, ITEM_KEYS, {"kind", "text", "list_position"}, item_path)
            kind = nonempty_string(raw_item["kind"], f"{item_path}.kind")
            if kind not in SURFACE_KINDS[surface]:
                raise ContractError(f"{item_path}.kind {kind!r} is not allowed for {surface!r}")
            text = nonempty_string(raw_item["text"], f"{item_path}.text")
            position = raw_item["list_position"]
            if isinstance(position, bool) or not isinstance(position, int) or position < 1:
                raise ContractError(f"{item_path}.list_position must be a positive integer")

            item: dict[str, Any] = {"kind": kind, "text": text, "list_position": position}
            for optional in ("category", "segment", "indicator_raw"):
                if optional in raw_item:
                    item[optional] = nonempty_string(raw_item[optional], f"{item_path}.{optional}")
            validated_items.append(item)

        validated.append(
            {
                "date": snapshot_date,
                "surface": surface,
                "status": status,
                "reason": reason.strip() if isinstance(reason, str) else None,
                "items": validated_items,
            }
        )
    return validated


def date_window(as_of: date, start_days_ago: int, end_days_ago: int) -> set[date]:
    return {as_of - timedelta(days=days) for days in range(start_days_ago, end_days_ago + 1)}


def range_object(days: set[date]) -> dict[str, str]:
    return {"start": min(days).isoformat(), "end": max(days).isoformat()}


def build_coverage(
    snapshots: list[dict[str, Any]],
    required_surfaces: list[str],
    recent_days: set[date],
    comparison_days: set[date],
) -> dict[str, Any]:
    indexed = {(snapshot["date"], snapshot["surface"]): snapshot for snapshot in snapshots}
    coverage: dict[str, Any] = {}
    for surface in required_surfaces:
        periods: dict[str, Any] = {}
        for name, days in (("recent", recent_days), ("comparison", comparison_days)):
            statuses = Counter()
            missing: list[str] = []
            for day in sorted(days):
                snapshot = indexed.get((day, surface))
                if snapshot is None:
                    missing.append(day.isoformat())
                else:
                    statuses[snapshot["status"]] += 1
            periods[name] = {
                "complete_days": statuses["complete"],
                "partial_days": statuses["partial"] + statuses["manual_partial"],
                "unavailable_days": statuses["unavailable"],
                "missing_days": missing,
            }
        coverage[surface] = periods
    return coverage


def fully_complete(coverage: dict[str, Any], surface: str, period: str) -> bool:
    item = coverage[surface][period]
    return (
        item["complete_days"] == 7
        and item["partial_days"] == 0
        and item["unavailable_days"] == 0
        and not item["missing_days"]
    )


def title_signals(text_value: str) -> tuple[set[str], set[str]]:
    normalized = unicodedata.normalize("NFKC", text_value)
    patterns = {name for name, rule in PATTERN_RULES.items() if rule.search(normalized)}
    sensitivities = {name for name, rule in SENSITIVITY_RULES.items() if rule.search(normalized)}
    return patterns, sensitivities


def trend_type(recent_count: int, prior_count: int, comparison_ready: bool) -> str:
    if not comparison_ready:
        if recent_count >= 4:
            return "persistent_observed"
        if recent_count >= 2:
            return "repeated_observed"
        return "one_day_observed"
    if recent_count >= 4:
        return "persistent"
    if prior_count == 0 and recent_count >= 2:
        return "emerging"
    if recent_count - prior_count >= 2:
        return "rising"
    if recent_count == 1:
        return "one_day"
    return "recurring"


def score_keyword(
    recent_dates: set[date],
    prior_dates: set[date],
    best_positions: dict[date, int],
    as_of: date,
    comparison_ready: bool,
) -> tuple[float, dict[str, float]]:
    recurrence = len(recent_dates) / 7 * 40
    weights = {as_of - timedelta(days=offset): 1.1 - offset * 0.1 for offset in range(1, 8)}
    recency = sum(weights.get(day, 0.0) for day in recent_dates) / sum(weights.values()) * 25
    daily_position_quality = [max(0.0, (51 - min(best_positions[day], 50)) / 50) for day in recent_dates]
    position = (sum(daily_position_quality) / len(daily_position_quality) * 15) if daily_position_quality else 0.0
    momentum = max(0, len(recent_dates) - len(prior_dates)) / 7 * 20 if comparison_ready else 0.0
    one_day_penalty = 10.0 if len(recent_dates) == 1 else 0.0
    total = max(0.0, min(100.0, recurrence + recency + position + momentum - one_day_penalty))
    components = {
        "recurrence": round(recurrence, 2),
        "recency": round(recency, 2),
        "list_position": round(position, 2),
        "comparison_change": round(momentum, 2),
        "one_day_penalty": round(one_day_penalty, 2),
    }
    return round(total, 2), components


def aggregate(
    document: dict[str, Any],
    as_of: date,
    limit: int = 10,
    required_surfaces: Iterable[str] = ("search_inflow", "main_inflow"),
) -> dict[str, Any]:
    snapshots = validate_document(document)
    required = list(dict.fromkeys(required_surfaces))
    if not required:
        raise ContractError("at least one required surface is needed")
    unsupported = [surface for surface in required if surface not in SURFACE_KINDS or surface == "manual"]
    if unsupported:
        raise ContractError(f"unsupported required surfaces: {', '.join(unsupported)}")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ContractError("limit must be between 1 and 1000")

    recent_days = date_window(as_of, 1, 7)
    comparison_days = date_window(as_of, 8, 14)
    in_scope_days = recent_days | comparison_days
    scoped_snapshots = [snapshot for snapshot in snapshots if snapshot["date"] in in_scope_days]
    ignored_count = len(snapshots) - len(scoped_snapshots)
    coverage = build_coverage(scoped_snapshots, required, recent_days, comparison_days)

    keyword_required_surfaces = [surface for surface in required if surface in {"search_inflow", "business"}]
    if "search_inflow" not in keyword_required_surfaces:
        keyword_required_surfaces.insert(0, "search_inflow")
        if "search_inflow" not in coverage:
            coverage.update(build_coverage(scoped_snapshots, ["search_inflow"], recent_days, comparison_days))
    comparison_ready = all(
        fully_complete(coverage, surface, period)
        for surface in keyword_required_surfaces
        for period in ("recent", "comparison")
    )

    keyword_occurrences: dict[str, list[dict[str, Any]]] = defaultdict(list)
    title_rows: set[tuple[date, str, str]] = set()
    pattern_counts: Counter[str] = Counter()
    sensitivity_counts: Counter[str] = Counter()

    for snapshot in scoped_snapshots:
        for item in snapshot["items"]:
            if item["kind"] in KEYWORD_KINDS:
                normalized = normalize_text(item["text"])
                keyword_occurrences[normalized].append(
                    {
                        "date": snapshot["date"],
                        "surface": snapshot["surface"],
                        "status": snapshot["status"],
                        **item,
                    }
                )
            elif item["kind"] in TITLE_KINDS and snapshot["date"] in recent_days:
                normalized_title = normalize_text(item["text"])
                row_key = (snapshot["date"], snapshot["surface"], normalized_title)
                if row_key in title_rows:
                    continue
                title_rows.add(row_key)
                patterns, sensitivities = title_signals(item["text"])
                pattern_counts.update(patterns)
                sensitivity_counts.update(sensitivities)

    recommendations: list[dict[str, Any]] = []
    for normalized, occurrences in keyword_occurrences.items():
        recent = [item for item in occurrences if item["date"] in recent_days]
        if not recent:
            continue
        prior = [item for item in occurrences if item["date"] in comparison_days]
        recent_dates_seen = {item["date"] for item in recent}
        prior_dates_seen = {item["date"] for item in prior}
        best_positions: dict[date, int] = {}
        for item in recent:
            best_positions[item["date"]] = min(best_positions.get(item["date"], item["list_position"]), item["list_position"])

        display = sorted(recent, key=lambda item: (item["date"], -item["list_position"]), reverse=True)[0]["text"]
        evidence_score, score_components = score_keyword(
            recent_dates_seen,
            prior_dates_seen,
            best_positions,
            as_of,
            comparison_ready,
        )
        categories = sorted({item["category"] for item in recent if item.get("category")})
        sources = sorted({item["surface"] for item in recent})
        segment_keys = {
            (item["surface"], item.get("category", ""), item.get("segment", "")) for item in recent
        }
        new_signal = any(normalize_text(item.get("indicator_raw", "")) == "new" for item in recent)
        recommendations.append(
            {
                "keyword": display,
                "normalized_keyword": normalized,
                "evidence_score": evidence_score,
                "score_components": score_components,
                "trend_type": trend_type(len(recent_dates_seen), len(prior_dates_seen), comparison_ready),
                "recent_days_seen": len(recent_dates_seen),
                "comparison_days_seen": len(prior_dates_seen),
                "recent_dates": [day.isoformat() for day in sorted(recent_dates_seen, reverse=True)],
                "sources": sources,
                "categories": categories,
                "new_signal_observed": new_signal,
                "segment_count": len(segment_keys),
            }
        )

    recommendations.sort(
        key=lambda item: (-item["evidence_score"], -item["recent_days_seen"], item["normalized_keyword"])
    )

    required_complete = all(
        fully_complete(coverage, surface, period)
        for surface in required
        for period in ("recent", "comparison")
    )
    if not recommendations:
        analysis_status = "unavailable"
    elif required_complete:
        analysis_status = "complete"
    else:
        analysis_status = "partial"

    limitations: list[str] = []
    if not comparison_ready:
        limitations.append("trend_windows_incomplete_no_rising_or_emerging_confirmation")
    if analysis_status == "partial":
        limitations.append("one_or_more_required_surfaces_incomplete")
    if ignored_count:
        limitations.append(f"ignored_out_of_window_snapshots:{ignored_count}")
    if any(snapshot["status"] == "manual_partial" for snapshot in scoped_snapshots):
        limitations.append("manual_partial_input")

    title_total = len(title_rows)
    title_patterns = [
        {
            "name": name,
            "count": count,
            "share": round(count / title_total, 4) if title_total else 0.0,
        }
        for name, count in sorted(pattern_counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]
    sensitivities = [
        {
            "name": name,
            "count": count,
            "share": round(count / title_total, 4) if title_total else 0.0,
        }
        for name, count in sorted(sensitivity_counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]

    return {
        "schema": OUTPUT_SCHEMA,
        "as_of": as_of.isoformat(),
        "analysis_status": analysis_status,
        "periods": {
            "recent": range_object(recent_days),
            "comparison": range_object(comparison_days),
        },
        "coverage": coverage,
        "comparison_ready": comparison_ready,
        "recommendations": recommendations[:limit],
        "title_pattern_summary": {
            "titles_observed": title_total,
            "patterns": title_patterns,
            "sensitivity_flags": sensitivities,
        },
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
    parser.add_argument("--input", type=Path, required=True, help="naver-creator-snapshots/v1 JSON")
    parser.add_argument("--output", type=Path, help="write keyword pack JSON; stdout when omitted")
    parser.add_argument("--as-of", required=True, help="analysis date in YYYY-MM-DD; today is excluded")
    parser.add_argument("--limit", type=int, default=10, help="maximum recommendations, 1-1000")
    parser.add_argument(
        "--required-surface",
        action="append",
        choices=("search_inflow", "main_inflow", "business"),
        help="surface required for complete status; repeat as needed",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    required_surfaces = args.required_surface or ["search_inflow", "main_inflow"]
    try:
        as_of = parse_date(args.as_of, "--as-of")
        result = aggregate(load_json(args.input), as_of, args.limit, required_surfaces)
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
