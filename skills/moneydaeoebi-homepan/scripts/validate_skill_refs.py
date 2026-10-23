#!/usr/bin/env python3
"""Validate local Markdown links inside this skill package."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


SKILL_ROOT = Path(__file__).resolve().parents[1]
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def local_target(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    target = target.split("#", 1)[0]
    if not target or "://" in target or target.startswith(("mailto:", "#")):
        return None
    return unquote(target)


def main() -> int:
    problems: list[str] = []
    markdown_files = sorted(SKILL_ROOT.rglob("*.md"))
    if SKILL_ROOT / "SKILL.md" not in markdown_files:
        problems.append("SKILL.md is missing")

    for source in markdown_files:
        text = source.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            target = local_target(match.group(1))
            if target is None:
                continue
            resolved = (source.parent / target).resolve()
            try:
                resolved.relative_to(SKILL_ROOT)
            except ValueError:
                problems.append(f"{source.relative_to(SKILL_ROOT)}: link escapes skill root: {target}")
                continue
            if not resolved.exists():
                problems.append(f"{source.relative_to(SKILL_ROOT)}: missing link target: {target}")

    if problems:
        print("Reference validation failed:")
        for problem in problems:
            print(f"- {problem}")
        return 1

    print(f"OK: checked {len(markdown_files)} Markdown files in {SKILL_ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
