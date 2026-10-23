#!/usr/bin/env python3
"""Audit mechanical and manifest-backed invariants in an R9 title set."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)")
NUMBERED_LIST_RE = re.compile(r"^\s*(\d+)[.)]\s+(.+)$")
NORMALIZE_RE = re.compile(r"[^0-9a-z가-힣]+", re.IGNORECASE)
LEADING_QUOTE_RE = re.compile(r"^[\"'“‘](.*?)[\"'”’]")
META_LABEL_RE = re.compile(r"\[([^\[\]]+)\]")
TRAILING_META_RE = re.compile(r"(?:\s+\[[^\[\]]+\])+\s*$")
N_LABEL_RE = re.compile(r"^무따옴표-(N[1-7])$")

QUOTE_LABELS = {"실제 발언", "독자 반응"}
CONDITIONAL_HOOKS = (
    "충격",
    "경악",
    "소름",
    "난리",
    "역대급",
    "대박",
    "이것",
    "이 사람",
    "그 이유",
    "비밀",
)
FORBIDDEN_HOOKS = (
    "모두가",
    "전국민",
    "결국 들통",
    "민낯",
    "무조건",
    "반드시",
)
VAGUE_HOOKS = (
    "따로 있었다",
    "알려진 건 여기까지",
    "총정리",
)
R9_STARTER_IDS = {f"S{index:02d}" for index in range(1, 31)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("titles", type=Path, help="UTF-8 file with one candidate title per line")
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--prefix-chars", type=int, default=6)
    parser.add_argument("--max-prefix-repeat", type=int, default=1)
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures")
    parser.add_argument("--r9", action="store_true", help="Enforce the fixed R9 50-title matrix")
    parser.add_argument(
        "--track",
        choices=("feed", "search", "mixed"),
        help="Title track; search allows a repeated leading search identifier",
    )
    parser.add_argument(
        "--feed",
        action="store_true",
        help="Deprecated alias for --track feed",
    )
    parser.add_argument(
        "--sensitive",
        action="store_true",
        help="Require sensitive-topic replacements and reject emotional hooks",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="R9 JSON manifest with per-topic S01-S30 candidates and selections",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def clean_title(line: str) -> str:
    return LIST_PREFIX_RE.sub("", line.strip()).strip("` ")


def normalized(title: str) -> str:
    return NORMALIZE_RE.sub("", title).lower()


def title_body(title: str) -> str:
    body = TRAILING_META_RE.sub("", title).strip()
    for marker in ("**", "__", "*", "_"):
        if body.startswith(marker) and body.endswith(marker) and len(body) > len(marker) * 2:
            body = body[len(marker) : -len(marker)].strip()
            break
    return body


def metadata_labels(title: str) -> list[str]:
    return [label.strip() for label in META_LABEL_RE.findall(title)]


def starter_labels(title: str) -> list[str]:
    labels: list[str] = []
    for label in metadata_labels(title):
        if label in QUOTE_LABELS or N_LABEL_RE.fullmatch(label):
            labels.append(label)
    return labels


def normalized_terms(title: str, terms: tuple[str, ...]) -> list[str]:
    value = normalized(title)
    return [term for term in terms if normalized(term) in value]


def read_titles(path: Path) -> tuple[list[str], list[str]]:
    titles: list[str] = []
    numbers: list[int] = []
    numbered_lines = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = NUMBERED_LIST_RE.match(stripped)
        if match:
            numbered_lines += 1
            numbers.append(int(match.group(1)))
        title = clean_title(stripped)
        if title:
            titles.append(title)

    errors: list[str] = []
    if numbered_lines and numbered_lines != len(titles):
        errors.append("candidate file must not mix numbered and unnumbered title lines")
    if numbered_lines and numbers != list(range(1, len(numbers) + 1)):
        errors.append("numbered candidate lines must be consecutive starting at 1")
    return titles, errors


def resolved_track(args: argparse.Namespace) -> tuple[str, list[str]]:
    errors: list[str] = []
    track = getattr(args, "track", None)
    feed_alias = bool(getattr(args, "feed", False))
    if feed_alias and track not in (None, "feed"):
        errors.append("--feed cannot be combined with a non-feed --track")
    if feed_alias:
        track = "feed"
    return track or "mixed", errors


def audit(titles: list[str], args: argparse.Namespace) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    track, track_errors = resolved_track(args)
    errors.extend(track_errors)

    title_bodies = [title_body(title) for title in titles]
    normalized_titles = [normalized(title) for title in title_bodies]

    expected_count = 50 if args.r9 else args.expected_count
    if expected_count is not None and len(titles) != expected_count:
        errors.append(f"expected {expected_count} titles, found {len(titles)}")

    duplicate_groups: dict[str, list[int]] = defaultdict(list)
    for index, value in enumerate(normalized_titles, start=1):
        duplicate_groups[value].append(index)
    duplicates = {value: indexes for value, indexes in duplicate_groups.items() if len(indexes) > 1}
    if duplicates:
        errors.append(f"normalized duplicate titles at indexes: {list(duplicates.values())}")

    if track != "search":
        prefix_groups: dict[str, list[int]] = defaultdict(list)
        for index, value in enumerate(normalized_titles, start=1):
            prefix = value[: args.prefix_chars]
            if prefix:
                prefix_groups[prefix].append(index)
        repeated_prefixes = {
            prefix: indexes
            for prefix, indexes in prefix_groups.items()
            if len(indexes) > args.max_prefix_repeat
        }
        if repeated_prefixes:
            warnings.append(
                f"repeated first-{args.prefix_chars}-character prefixes: {repeated_prefixes}"
            )

    vague_indexes: dict[str, list[int]] = defaultdict(list)
    for index, body in enumerate(title_bodies, start=1):
        for hook in normalized_terms(body, VAGUE_HOOKS):
            vague_indexes[hook].append(index)
    if vague_indexes:
        warnings.append(f"vague hook phrases: {dict(vague_indexes)}")

    count = len(titles)
    question_count = sum(title.rstrip().endswith("?") for title in title_bodies)
    ellipsis_count = sum("…" in title or "..." in title for title in title_bodies)
    quote_flags = [title.startswith(("\"", "'", "“", "‘")) for title in title_bodies]
    quote_count = sum(quote_flags)
    emotion_title_count = 0
    conditional_by_index: dict[int, list[str]] = {}
    n_label_counts: Counter[str] = Counter()

    for index, body in enumerate(title_bodies, start=1):
        forbidden = normalized_terms(body, FORBIDDEN_HOOKS)
        if forbidden:
            errors.append(f"title {index} contains forbidden hook(s): {forbidden}")

        conditional = normalized_terms(body, CONDITIONAL_HOOKS)
        conditional_by_index[index] = conditional
        if len(conditional) > 1:
            errors.append(
                f"title {index} contains more than one conditional emotional hook: {conditional}"
            )
        if conditional:
            emotion_title_count += 1
        if getattr(args, "sensitive", False) and conditional:
            errors.append(
                f"sensitive title {index} must not use emotional or demonstrative hooks: {conditional}"
            )

    if args.r9:
        unquoted_count = count - quote_count
        if quote_count != 20 or unquoted_count != 30:
            errors.append(
                "R9 quote allocation must be exactly 20 quoted and 30 unquoted "
                f"(found {quote_count}/{unquoted_count})"
            )

        per_title_starter: list[str | None] = []
        for index, (title, body, is_quoted) in enumerate(
            zip(titles, title_bodies, quote_flags), start=1
        ):
            labels = starter_labels(title)
            if len(labels) != 1:
                errors.append(
                    f"title {index} must have exactly one starter label "
                    "([실제 발언], [독자 반응], or [무따옴표-N1..N7])"
                )
                per_title_starter.append(None)
                continue

            label = labels[0]
            per_title_starter.append(label)
            n_match = N_LABEL_RE.fullmatch(label)
            if is_quoted:
                if label not in QUOTE_LABELS:
                    errors.append(f"quoted title {index} cannot use starter label [{label}]")
                quote_match = LEADING_QUOTE_RE.match(body)
                if not quote_match:
                    errors.append(f"quoted title {index} has an unmatched leading quotation mark")
                elif label == "독자 반응" and not quote_match.group(1).strip().endswith("?"):
                    errors.append(f"reader-reaction title {index} must end its quoted starter with ?")
            else:
                if not n_match:
                    errors.append(f"unquoted title {index} must use a [무따옴표-N1..N7] label")
                else:
                    n_label_counts[n_match.group(1)] += 1

        if count == 50:
            for group_index in range(10):
                start = group_index * 5
                group_quotes = sum(quote_flags[start : start + 5])
                if group_quotes != 2:
                    errors.append(
                        f"R9 group {group_index + 1} must contain 2 quoted and 3 unquoted "
                        f"titles (found {group_quotes}/{5 - group_quotes})"
                    )
                group_n_labels = [
                    match.group(1)
                    for label in per_title_starter[start : start + 5]
                    if label is not None
                    for match in [N_LABEL_RE.fullmatch(label)]
                    if match
                ]
                if len(group_n_labels) == 3 and len(set(group_n_labels)) != 3:
                    errors.append(
                        f"R9 group {group_index + 1} must use three different unquoted N labels"
                    )

        if ellipsis_count > 25:
            errors.append(f"R9 ellipsis limit exceeded: {ellipsis_count}/50 (max 25)")

        quoted_starters = []
        for body in title_bodies:
            match = LEADING_QUOTE_RE.match(body)
            if match:
                quoted_starters.append(match.group(1).strip())

        rago_count = sum(starter.endswith("라고?") for starter in quoted_starters)
        neunde_count = sum(starter.endswith("는데?") for starter in quoted_starters)
        why_ji_count = sum(bool(re.search(r"왜.*지\?$", starter)) for starter in quoted_starters)
        if rago_count > 7:
            errors.append(f"R9 '~라고?' starter limit exceeded: {rago_count}/20 (max 7)")
        if neunde_count > 4:
            errors.append(
                f"R9 '~는데?/~줄 알았는데?' starter limit exceeded: {neunde_count}/20 (max 4)"
            )
        if why_ji_count > 2:
            errors.append(f"R9 '왜 ~지?' starter limit exceeded: {why_ji_count}/20 (max 2)")

        if emotion_title_count > 10:
            errors.append(
                f"R9 conditional emotional-hook limit exceeded: {emotion_title_count}/50 (max 10)"
            )

        if count == 50:
            for index in range(46, 51):
                labels = metadata_labels(titles[index - 1])
                conditional = conditional_by_index[index]
                if getattr(args, "sensitive", False):
                    if "민감대체" not in labels:
                        errors.append(
                            f"sensitive R9 group-10 title {index} requires a [민감대체] label"
                        )
                elif not conditional and "감정대체" not in labels:
                    errors.append(
                        f"R9 group-10 title {index} requires one conditional emotional hook "
                        "or a [감정대체] label"
                    )

        if track == "feed":
            if n_label_counts["N6"] < 5:
                errors.append(
                    f"R9 feed titles require at least 5 valid unquoted N6 starters "
                    f"(found {n_label_counts['N6']})"
                )
            if n_label_counts["N7"] < 5:
                errors.append(
                    f"R9 feed titles require at least 5 valid unquoted N7 starters "
                    f"(found {n_label_counts['N7']})"
                )

    if count >= 4 and question_count / count > 0.5:
        warnings.append(f"question endings dominate the set: {question_count}/{count}")
    if count >= 4 and ellipsis_count / count > 0.5:
        warnings.append(f"ellipsis titles dominate the set: {ellipsis_count}/{count}")
    if count >= 4 and quote_count / count > 0.5:
        warnings.append(f"quoted starters dominate the set: {quote_count}/{count}")

    ending_tokens = [value[-4:] if len(value) >= 4 else value for value in normalized_titles]
    repeated_endings = {
        ending: amount for ending, amount in Counter(ending_tokens).items() if amount >= 3
    }
    if repeated_endings:
        warnings.append(f"repeated normalized endings: {repeated_endings}")

    return {
        "ok": not errors and (not warnings or not args.strict),
        "title_count": count,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "track": track,
            "question_count": question_count,
            "ellipsis_count": ellipsis_count,
            "quoted_starter_count": quote_count,
            "unquoted_starter_count": count - quote_count,
            "conditional_emotional_title_count": emotion_title_count,
            "n_label_counts": dict(sorted(n_label_counts.items())),
        },
    }


def audit_manifest(data: Any, titles: list[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["R9 manifest root must be a JSON object"]

    topics = data.get("topics")
    if not isinstance(topics, list) or not topics:
        errors.append("R9 manifest topics must be a non-empty list")
    else:
        for topic_index, topic in enumerate(topics, start=1):
            if not isinstance(topic, dict):
                errors.append(f"manifest topic {topic_index} must be an object")
                continue
            topic_name = topic.get("topic")
            if not isinstance(topic_name, str) or not topic_name.strip():
                errors.append(f"manifest topic {topic_index} requires a non-empty topic name")

            title_numbers = topic.get("title_numbers")
            if (
                not isinstance(title_numbers, list)
                or not title_numbers
                or any(not isinstance(number, int) or not 1 <= number <= 50 for number in title_numbers)
            ):
                errors.append(
                    f"manifest topic {topic_index} requires one or more title_numbers from 1 to 50"
                )

            starters = topic.get("starters")
            if not isinstance(starters, dict):
                errors.append(f"manifest topic {topic_index} starters must be an object")
                continue
            starter_keys = set(starters)
            missing = sorted(R9_STARTER_IDS - starter_keys)
            extra = sorted(starter_keys - R9_STARTER_IDS)
            if missing:
                errors.append(f"manifest topic {topic_index} missing starter IDs: {missing}")
            if extra:
                errors.append(f"manifest topic {topic_index} has unknown starter IDs: {extra}")

            candidate_values = []
            for starter_id in sorted(R9_STARTER_IDS & starter_keys):
                candidate = starters[starter_id]
                if not isinstance(candidate, str) or not candidate.strip():
                    errors.append(
                        f"manifest topic {topic_index} starter {starter_id} requires a raw candidate"
                    )
                else:
                    candidate_values.append(normalized(candidate))
            duplicates = [
                value for value, amount in Counter(candidate_values).items() if value and amount > 1
            ]
            if duplicates:
                errors.append(
                    f"manifest topic {topic_index} reuses identical raw candidates across starter IDs"
                )

    def validate_selection(entry: Any, label: str) -> tuple[int | None, str | None]:
        if not isinstance(entry, dict):
            errors.append(f"manifest {label} entry must be an object")
            return None, None
        number = entry.get("number")
        selected_title = entry.get("title")
        if not isinstance(number, int) or not 1 <= number <= len(titles):
            errors.append(f"manifest {label} number must reference an existing title")
            return None, None
        if not isinstance(selected_title, str):
            errors.append(f"manifest {label} title must be a string")
            return number, None
        expected = title_body(titles[number - 1])
        if selected_title != expected:
            errors.append(
                f"manifest {label} title does not exactly match candidate {number} after labels"
            )
        return number, selected_title

    top5 = data.get("top5")
    top5_numbers: list[int] = []
    if not isinstance(top5, list) or len(top5) != 5:
        errors.append("R9 manifest top5 must contain exactly five selections")
    else:
        for index, entry in enumerate(top5, start=1):
            number, _ = validate_selection(entry, f"top5[{index}]")
            if number is not None:
                top5_numbers.append(number)
        if len(set(top5_numbers)) != len(top5_numbers):
            errors.append("R9 manifest top5 numbers must be unique")
        groups = {(number - 1) // 5 + 1 for number in top5_numbers}
        if len(top5_numbers) == 5 and len(groups) != 5:
            errors.append("R9 manifest top5 must come from five different groups")

    final_number, _ = validate_selection(data.get("final"), "final")
    if final_number is not None and top5_numbers and final_number not in top5_numbers:
        errors.append("R9 manifest final selection must be one of the TOP5 numbers")

    return errors


def load_manifest(path: Path) -> tuple[Any | None, list[str]]:
    if not path.is_file():
        return None, [f"manifest file not found: {path}"]
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"could not read R9 manifest: {exc}"]


def main() -> int:
    args = parse_args()
    if not args.titles.is_file():
        print(f"title file not found: {args.titles}", file=sys.stderr)
        return 2

    titles, parse_errors = read_titles(args.titles)
    result = audit(titles, args)
    result["errors"].extend(parse_errors)

    if args.r9 and args.manifest is None:
        result["errors"].append("--manifest is required with --r9")
    elif args.manifest is not None:
        manifest, manifest_errors = load_manifest(args.manifest)
        result["errors"].extend(manifest_errors)
        if manifest is not None:
            result["errors"].extend(audit_manifest(manifest, titles))

    result["ok"] = not result["errors"] and (not result["warnings"] or not args.strict)

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Titles: {result['title_count']}")
        for error in result["errors"]:
            print(f"ERROR: {error}")
        for warning in result["warnings"]:
            print(f"WARNING: {warning}")
        if result["ok"]:
            print("OK")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
