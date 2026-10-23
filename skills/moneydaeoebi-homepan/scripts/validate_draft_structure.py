#!/usr/bin/env python3
"""Check mechanical structure of a Naver post draft."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD)\b|\[(?:출처|확인|내용)\s*(?:필요|입력)\]", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("--expected-title")
    parser.add_argument("--expected-headings", type=int)
    parser.add_argument("--require-hashtags", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Fail on unfinished placeholders.")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def inspect(text: str, args: argparse.Namespace) -> tuple[list[str], dict[str, object]]:
    lines = text.splitlines()
    nonempty = [line.strip() for line in lines if line.strip()]
    errors: list[str] = []

    if not nonempty:
        return ["draft is empty"], {"title": None, "heading_count": 0, "has_hashtags": False}

    title = nonempty[0]
    if title.startswith("#"):
        errors.append("first non-empty line must be a plain title, not a Markdown heading")
    if title.startswith(("제목:", "본문:")):
        errors.append("do not prefix the post with 제목: or 본문:")
    if args.expected_title and title != args.expected_title:
        errors.append("first line does not match --expected-title")

    headings = [line[3:].strip() for line in lines if line.startswith("## ")]
    empty_headings = [line for line in lines if line.strip() == "##"]
    if empty_headings:
        errors.append("one or more level-two headings are empty")
    if len(headings) != len(set(headings)):
        errors.append("level-two headings must be unique")
    if args.expected_headings is not None and len(headings) != args.expected_headings:
        errors.append(
            f"expected {args.expected_headings} level-two headings, found {len(headings)}"
        )

    if any(line.startswith("# ") for line in lines):
        errors.append("do not add an H1; use a plain title line")
    if text.count("```") % 2:
        errors.append("Markdown code fences are unbalanced")

    has_hashtags = any(
        line.strip().startswith("#") and not line.startswith("##") for line in lines[1:]
    )
    if args.require_hashtags and not has_hashtags:
        errors.append("a hashtag line is required")
    if args.strict and PLACEHOLDER_RE.search(text):
        errors.append("unfinished placeholder found")

    metadata: dict[str, object] = {
        "title": title,
        "heading_count": len(headings),
        "headings": headings,
        "has_hashtags": has_hashtags,
    }
    return errors, metadata


def main() -> int:
    args = parse_args()
    if not args.draft.is_file():
        print(f"draft not found: {args.draft}", file=sys.stderr)
        return 2

    errors, metadata = inspect(args.draft.read_text(encoding="utf-8"), args)
    result = {"ok": not errors, "errors": errors, **metadata}

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print("Draft structure validation failed:")
        for error in errors:
            print(f"- {error}")
    else:
        print(
            f"OK: title={metadata['title']!r}, headings={metadata['heading_count']}, "
            f"hashtags={metadata['has_hashtags']}"
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
