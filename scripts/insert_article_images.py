#!/usr/bin/env python3
"""Insert approved local images into explicit Naver Blog Markdown slots."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence


RAW_MARKER_RE = re.compile(r"<!--\s*naver-image:([^>]*)-->")
SLOT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ALLOWED_ROLES = {"cover", "inline"}
ALLOWED_MODES = {
    "photorealistic-natural",
    "infographic-diagram",
    "stylized-concept",
    "ui-mockup",
}
REQUIRED_SLOT_FIELDS = {
    "id",
    "role",
    "placement",
    "purpose",
    "mode",
    "prompt",
    "alt",
    "caption",
    "path",
    "status",
}


class CompositionError(ValueError):
    """Raised when an article or image manifest is unsafe or inconsistent."""


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_cli_path(value: str | Path, root: Path, field: str) -> Path:
    path = Path(value)
    candidate = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not _is_within(candidate, root):
        raise CompositionError(f"{field} must stay inside the project root: {value}")
    return candidate


def _resolve_relative_path(value: Any, root: Path, field: str) -> tuple[Path, str]:
    if not isinstance(value, str) or not value.strip():
        raise CompositionError(f"{field} must be a non-empty relative path")
    if any(char in value for char in ("\n", "\r", "\x00", "<", ">")):
        raise CompositionError(f"{field} contains unsupported characters: {value!r}")

    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise CompositionError(f"{field} must be project-relative and must not contain '..': {value}")

    candidate = (root / path).resolve()
    if not _is_within(candidate, root):
        raise CompositionError(f"{field} escapes the project root: {value}")
    return candidate, path.as_posix()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CompositionError(f"Unable to read manifest {path}: {exc}") from exc

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CompositionError(
            f"Invalid JSON in manifest {path} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(value, dict):
        raise CompositionError("Manifest root must be a JSON object")
    return value


def _require_single_line(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CompositionError(f"{field} must be a string")
    if not allow_empty and not value.strip():
        raise CompositionError(f"{field} must not be empty")
    if "\n" in value or "\r" in value or "\x00" in value:
        raise CompositionError(f"{field} must be a single line")
    return value


def _validate_manifest(data: dict[str, Any], root: Path) -> list[dict[str, str]]:
    if data.get("version") != 1:
        raise CompositionError("Manifest version must be 1")

    asset_root_path, asset_root_text = _resolve_relative_path(
        data.get("asset_root"), root, "asset_root"
    )
    if not asset_root_path.is_dir():
        raise CompositionError(f"asset_root directory does not exist: {asset_root_text}")

    raw_slots = data.get("slots")
    if not isinstance(raw_slots, list) or not raw_slots:
        raise CompositionError("Manifest slots must be a non-empty array")

    slots: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, raw_slot in enumerate(raw_slots):
        label = f"slots[{index}]"
        if not isinstance(raw_slot, dict):
            raise CompositionError(f"{label} must be an object")

        missing = REQUIRED_SLOT_FIELDS - raw_slot.keys()
        if missing:
            raise CompositionError(f"{label} is missing fields: {', '.join(sorted(missing))}")

        slot_id = _require_single_line(raw_slot["id"], f"{label}.id")
        if not SLOT_ID_RE.fullmatch(slot_id):
            raise CompositionError(
                f"{label}.id must match {SLOT_ID_RE.pattern}: {slot_id!r}"
            )
        if slot_id in seen_ids:
            raise CompositionError(f"Duplicate manifest slot ID: {slot_id}")
        seen_ids.add(slot_id)

        role = _require_single_line(raw_slot["role"], f"{label}.role")
        if role not in ALLOWED_ROLES:
            raise CompositionError(f"{label}.role must be one of {sorted(ALLOWED_ROLES)}")

        mode = _require_single_line(raw_slot["mode"], f"{label}.mode")
        if mode not in ALLOWED_MODES:
            raise CompositionError(f"{label}.mode must be one of {sorted(ALLOWED_MODES)}")

        status = _require_single_line(raw_slot["status"], f"{label}.status")
        if status != "approved":
            raise CompositionError(f"Slot {slot_id} is not approved: {status}")

        image_path, image_path_text = _resolve_relative_path(
            raw_slot["path"], root, f"{label}.path"
        )
        if not _is_within(image_path, asset_root_path):
            raise CompositionError(
                f"Slot {slot_id} path must stay inside asset_root {asset_root_text}: {image_path_text}"
            )
        if not image_path.is_file():
            raise CompositionError(f"Image file for slot {slot_id} does not exist: {image_path_text}")

        normalized = {
            "id": slot_id,
            "role": role,
            "placement": _require_single_line(
                raw_slot["placement"], f"{label}.placement"
            ),
            "purpose": _require_single_line(raw_slot["purpose"], f"{label}.purpose"),
            "mode": mode,
            "prompt": _require_single_line(raw_slot["prompt"], f"{label}.prompt"),
            "alt": _require_single_line(raw_slot["alt"], f"{label}.alt"),
            "caption": _require_single_line(
                raw_slot["caption"], f"{label}.caption", allow_empty=True
            ),
            "path": image_path_text,
            "status": status,
        }
        slots.append(normalized)

    return slots


def _extract_marker_ids(article: str) -> list[str]:
    marker_ids: list[str] = []
    seen: set[str] = set()
    for match in RAW_MARKER_RE.finditer(article):
        slot_id = match.group(1).strip()
        if not SLOT_ID_RE.fullmatch(slot_id):
            raise CompositionError(f"Invalid article marker ID: {slot_id!r}")
        if slot_id in seen:
            raise CompositionError(f"Duplicate article marker ID: {slot_id}")
        seen.add(slot_id)
        marker_ids.append(slot_id)

    if not marker_ids:
        raise CompositionError("Article contains no naver-image markers")
    return marker_ids


def _escape_alt(value: str) -> str:
    return value.replace("\\", "\\\\").replace("]", "\\]")


def _escape_caption(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("*", "\\*")
        .replace("_", "\\_")
    )


def _markdown_block(slot: dict[str, str]) -> str:
    block = f"![{_escape_alt(slot['alt'])}](<{slot['path']}>)"
    if slot["caption"]:
        block += f"\n\n*{_escape_caption(slot['caption'])}*"
    return block


def _compose_text(article: str, slots: list[dict[str, str]]) -> str:
    marker_ids = _extract_marker_ids(article)
    manifest_ids = [slot["id"] for slot in slots]

    marker_set = set(marker_ids)
    manifest_set = set(manifest_ids)
    missing_manifest = [slot_id for slot_id in marker_ids if slot_id not in manifest_set]
    missing_marker = [slot_id for slot_id in manifest_ids if slot_id not in marker_set]
    if missing_manifest or missing_marker:
        details: list[str] = []
        if missing_manifest:
            details.append("markers without manifest slots: " + ", ".join(missing_manifest))
        if missing_marker:
            details.append("manifest slots without markers: " + ", ".join(missing_marker))
        raise CompositionError("Slot mismatch: " + "; ".join(details))

    if marker_ids != manifest_ids:
        raise CompositionError(
            "Manifest slot order must match article marker order: "
            f"article={marker_ids}, manifest={manifest_ids}"
        )

    slots_by_id = {slot["id"]: slot for slot in slots}

    def replace(match: re.Match[str]) -> str:
        slot_id = match.group(1).strip()
        return _markdown_block(slots_by_id[slot_id])

    return RAW_MARKER_RE.sub(replace, article)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            temporary = Path(handle.name)
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def compose_article(
    article_path: str | Path,
    manifest_path: str | Path,
    output_path: str | Path,
    *,
    force: bool = False,
    root: str | Path | None = None,
) -> int:
    project_root = Path.cwd().resolve() if root is None else Path(root).resolve()
    if not project_root.is_dir():
        raise CompositionError(f"Project root does not exist: {project_root}")

    article = _resolve_cli_path(article_path, project_root, "article")
    manifest = _resolve_cli_path(manifest_path, project_root, "manifest")
    output = _resolve_cli_path(output_path, project_root, "out")

    if not article.is_file():
        raise CompositionError(f"Article file does not exist: {article}")
    if not manifest.is_file():
        raise CompositionError(f"Manifest file does not exist: {manifest}")
    if output.exists() and not force:
        raise CompositionError(f"Output already exists; use --force to replace it: {output}")

    try:
        article_text = article.read_text(encoding="utf-8")
    except OSError as exc:
        raise CompositionError(f"Unable to read article {article}: {exc}") from exc

    data = _load_json(manifest)
    slots = _validate_manifest(data, project_root)
    composed = _compose_text(article_text, slots)
    _atomic_write(output, composed)
    return len(slots)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Insert approved local images into explicit Naver Blog Markdown slots."
    )
    parser.add_argument("--article", required=True, help="Markdown article containing slot markers")
    parser.add_argument("--manifest", required=True, help="Image manifest JSON v1")
    parser.add_argument("--out", required=True, help="New composed Markdown output path")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing output file, including the article when explicitly selected",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        inserted = compose_article(
            args.article,
            args.manifest,
            args.out,
            force=args.force,
        )
    except CompositionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Inserted {inserted} image slot(s): {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
