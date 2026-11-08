#!/usr/bin/env python3
"""Measure one Naver manuscript and gate new full-length content without mutating it."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/naver-series-workflow/scripts'))
sys.path.insert(0, str(ROOT / 'skills/naver-smarteditor-drafter/scripts'))
sys.path.insert(0, str(ROOT / 'scripts'))
from content_metrics import body_metrics, visible_body_text
from build_naver_post import parse_markdown
from insert_article_images import RAW_MARKER_RE


def check_length(post: dict, *, mode: str, minimum: int | None = None,
                 excluded_block_ids: tuple[str, ...] = ()) -> dict:
    """Gate full articles; explicit brief and existing preservation are separate modes."""
    if mode not in {'full', 'explicit', 'preserve'}:
        raise ValueError('invalid mode')
    if minimum is not None and (type(minimum) is not int or minimum < 1):
        raise ValueError('minimum must be a positive integer')
    if mode != 'explicit' and minimum is not None:
        raise ValueError('minimum applies only to explicit mode')
    metrics = body_metrics(post, excluded_block_ids=excluded_block_ids)
    text = visible_body_text(post, excluded_block_ids=excluded_block_ids)
    count = metrics['body_char_count']
    threshold = 3000 if mode == 'full' else minimum
    if mode == 'preserve':
        status = 'not_applicable'
    elif not count:
        status = 'failed'
    elif threshold is None:
        status = 'measured'
    else:
        status = 'passed' if count >= threshold else 'failed'
    return {'schema': 'naver-body-length-gate/v1', 'mode': mode, 'status': status,
            'body_char_count': count, 'body_char_count_without_whitespace': sum(not c.isspace() for c in text),
            'minimum': threshold, 'shortfall': max(0, threshold - count) if threshold is not None else None,
            'metrics': metrics, 'meaning_review': 'not_evaluated'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path, help='Markdown or naver-post/v1 JSON')
    parser.add_argument('--project-root', required=True, type=Path)
    parser.add_argument('--mode', required=True, choices=['full', 'explicit', 'preserve'])
    parser.add_argument('--minimum', type=int, help='explicitly requested minimum only')
    parser.add_argument('--exclude-block-id', action='append', default=[], help='verified caption block id')
    args = parser.parse_args()
    try:
        raw = args.input.read_bytes()
        if args.input.suffix.lower() == '.json':
            post = json.loads(raw)
            if not isinstance(post, dict) or post.get('schema') != 'naver-post/v1' or not isinstance(post.get('blocks'), list):
                raise ValueError('expected naver-post/v1 JSON with blocks')
        elif args.input.suffix.lower() == '.md':
            text = RAW_MARKER_RE.sub('', raw.decode('utf-8'))
            post, _ = parse_markdown(args.input, args.project_root, text=text)
        else:
            raise ValueError('input must be .md or .json')
        if args.exclude_block_id:
            ids = [b.get('id') for b in post['blocks'] if isinstance(b, dict)]
            if len(ids) != len(set(ids)) or any(i not in ids for i in args.exclude_block_id):
                raise ValueError('excluded block IDs must be unique and present in the canonical post')
        result = check_length(post, mode=args.mode, minimum=args.minimum,
                              excluded_block_ids=tuple(args.exclude_block_id))
        result.update(source_path=str(args.input.resolve()), source_sha256=hashlib.sha256(raw).hexdigest())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result['status'] == 'failed' else 0
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(json.dumps({'schema': 'naver-body-length-gate/v1', 'status': 'error', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
