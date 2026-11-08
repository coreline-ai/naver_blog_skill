#!/usr/bin/env python3
"""Recheck a prepared drafter snapshot's length, source and asset identity.

This is a local integrity/length gate, not a factual review or UI authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from asset_integrity import verify_asset
from build_naver_post import CONTENT_MODES, DEFAULT_MIN_BODY_CHARS, content_revision
from post_contract import BuildError, load_json_object, validate_post

METRICS = Path(__file__).resolve().parents[2] / 'naver-series-workflow' / 'scripts'
if not (METRICS / 'content_metrics.py').is_file():
    raise SystemExit('content metrics dependency missing; verification not performed')
sys.path.insert(0, str(METRICS))
from content_metrics import body_metrics  # noqa: E402


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(run_directory: Path, project_root: Path) -> dict:
    directory = Path(run_directory).resolve()
    root = Path(project_root).resolve()
    if not directory.is_dir() or not directory.is_relative_to(root):
        raise BuildError('prepared run must be inside the project root', 'UNSAFE_PATH')
    marker = load_json_object(directory / 'complete.json')
    if marker.get('schema') != 'naver-prepared-snapshot/v1' or not isinstance(marker.get('files'), dict):
        raise BuildError('prepared snapshot marker missing or invalid', 'SNAPSHOT_INVALID')
    files = marker['files']
    if 'run-report.json' not in files:
        raise BuildError('run report missing from snapshot', 'SNAPSHOT_INVALID')
    for name, digest in files.items():
        relative = Path(name)
        path = directory / relative
        if relative.is_absolute() or '..' in relative.parts or path.is_symlink() or not path.resolve().is_relative_to(directory) or not path.is_file():
            raise BuildError('snapshot path is invalid', 'SNAPSHOT_INVALID')
        if not isinstance(digest, str) or _hash(path) != digest:
            raise BuildError(f'snapshot file changed: {name}', 'SNAPSHOT_CHANGED')
    report = load_json_object(directory / 'run-report.json')
    mode = report.get('content_mode')
    if report.get('status') != 'prepared' or report.get('totals', {}).get('failed') != 0 or mode not in CONTENT_MODES:
        raise BuildError('run is not fully prepared with an explicit content mode', 'RUN_NOT_READY')
    sources = report.get('episodes')
    if not isinstance(sources, list) or len(sources) != report.get('totals', {}).get('prepared') or not sources:
        raise BuildError('prepared episode list mismatch', 'SNAPSHOT_INVALID')
    preflights = sorted(name for name in files if name.endswith('/preflight-report.json'))
    if len(preflights) != len(sources):
        raise BuildError('prepared episode files mismatch', 'SNAPSHOT_INVALID')
    results = []
    for name in preflights:
        folder = (directory / name).parent
        for sibling in ('naver-post.json', 'asset-integrity.json'):
            if str((folder / sibling).relative_to(directory)) not in files:
                raise BuildError('required episode artifact missing from snapshot', 'SNAPSHOT_INVALID')
        preflight = load_json_object(directory / name)
        post = load_json_object(folder / 'naver-post.json')
        validate_post(post)
        asset_file = load_json_object(folder / 'asset-integrity.json')
        assets = asset_file.get('assets')
        if not isinstance(assets, list) or assets != preflight.get('asset_integrity'):
            raise BuildError('asset evidence mismatch', 'SNAPSHOT_INVALID')
        if len(assets) != sum(block['type'] == 'image' for block in post['blocks']):
            raise BuildError('asset count mismatch', 'SNAPSHOT_INVALID')
        for asset in assets:
            verify_asset(asset, root)
        source = Path(preflight.get('source', '')).resolve()
        if not source.is_relative_to(root) or not source.is_file() or _hash(source) != preflight.get('source_sha256'):
            raise BuildError('source changed since preparation; reprepare and review', 'SOURCE_CHANGED')
        # Canonical JSON preserves its original provenance in post.source; the
        # current prepared input is tracked separately by preflight.source.
        if not any(entry.get('source') == str(source) and entry.get('episode') == post.get('episode') and entry.get('title') == post.get('title') and entry.get('status') == 'prepared' for entry in sources):
            raise BuildError('prepared source identity mismatch', 'SNAPSHOT_INVALID')
        if preflight.get('status') != 'passed' or preflight.get('content_mode') != mode:
            raise BuildError('preflight mode or status mismatch', 'RUN_NOT_READY')
        if content_revision(post, assets, render_policy=preflight.get('render_policy')) != preflight.get('content_revision'):
            raise BuildError('content revision changed', 'REVISION_CHANGED')
        recorded_metrics = preflight.get('body_metrics')
        if not isinstance(recorded_metrics, dict) or not isinstance(recorded_metrics.get('excluded_block_ids'), list):
            raise BuildError('caption exclusions unavailable', 'METRICS_CHANGED')
        ids = [block['id'] for block in post['blocks']]
        excluded = recorded_metrics['excluded_block_ids']
        if len(set(excluded)) != len(excluded):
            raise BuildError('duplicate caption exclusions', 'INVALID_CAPTION_BLOCK')
        for caption_id in excluded:
            if caption_id not in ids:
                raise BuildError('caption block missing', 'INVALID_CAPTION_BLOCK')
            index = ids.index(caption_id)
            if index < 1 or post['blocks'][index]['type'] != 'paragraph' or post['blocks'][index - 1]['type'] != 'image':
                raise BuildError('invalid caption block', 'INVALID_CAPTION_BLOCK')
        metrics = body_metrics(post, excluded_block_ids=excluded)
        if metrics != recorded_metrics:
            raise BuildError('body metrics do not match this revision', 'METRICS_CHANGED')
        if mode == 'full':
            minimum = preflight.get('min_body_chars')
            if type(minimum) is not int or minimum < DEFAULT_MIN_BODY_CHARS or metrics['body_char_count'] < minimum or preflight.get('length_ready') is not True:
                raise BuildError('full article length gate failed', 'BODY_TOO_SHORT')
        else:
            if not isinstance(preflight.get('scope_evidence'), str) or not preflight['scope_evidence'].strip():
                raise BuildError('short or exact-input mode lacks explicit scope evidence', 'SCOPE_EVIDENCE_REQUIRED')
            explicit_minimum = preflight.get('explicit_minimum')
            if explicit_minimum is not None:
                if mode != 'explicit' or type(explicit_minimum) is not int or explicit_minimum < 1 or metrics['body_char_count'] < explicit_minimum or preflight.get('length_ready') is not True:
                    raise BuildError('explicit minimum not met', 'BODY_TOO_SHORT')
            elif preflight.get('length_ready') is not None:
                raise BuildError('unmeasured threshold cannot be reported as passed', 'METRICS_CHANGED')
        results.append({'title': post['title'], 'body_char_count': metrics['body_char_count'],
                        'content_revision': preflight['content_revision'], 'length_ready': preflight['length_ready']})
    return {'status': 'passed', 'content_mode': mode, 'episodes': results,
            'factual_review': 'not_evaluated', 'ui_authorized': False,
            'note': 'Length and local integrity only; independently verify user intent, review and UI state.'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory', required=True)
    parser.add_argument('--project-root', required=True)
    args = parser.parse_args()
    try:
        result = verify(Path(args.run_directory), Path(args.project_root))
    except (BuildError, OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc), 'error_code': getattr(exc, 'code', 'READ_ERROR')}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
