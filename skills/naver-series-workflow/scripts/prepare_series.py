#!/usr/bin/env python3
"""Read-only input preparation/status. No LLM, image generation, or browser driver."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

SKILLS = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
DRAFTER = SKILLS / 'naver-smarteditor-drafter'
if not (DRAFTER / 'scripts/post_contract.py').is_file():
    raise SystemExit('DEPENDENCY_MISSING: sibling naver-smarteditor-drafter; no automatic installation')
sys.path.insert(0, str(DRAFTER / 'scripts'))
from post_contract import BuildError, load_json_object, require_int, require_text, safe_segment, validate_post
from build_naver_post import build_post, preflight_report, content_revision, safe_run_directory, write_prepared_run
from asset_integrity import verify_asset
from execution_state import ExecutionKey, ExecutionStore

REVIEW_CHECKS = {'factuality', 'originality', 'image_relevance', 'editorial_boundary'}
SHA = re.compile(r'[a-f0-9]{64}')


def encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fields(value: Any, required: set[str], optional: set[str], label: str) -> dict:
    if not isinstance(value, dict) or required - value.keys() or value.keys() - required - optional:
        raise BuildError(f'{label}: missing or unsupported fields', 'INVALID_CONTRACT')
    return value


def input_path(value: Any, base: Path, root: Path) -> Path:
    require_text(value, 'input path')
    raw = Path(value)
    path = (raw if raw.is_absolute() else base / raw).resolve()
    if not path.is_relative_to(root):
        raise BuildError('input path escapes allowed root', 'UNSAFE_PATH')
    return path


def source_record(path: Path) -> dict:
    return {'path': str(path), 'sha256': sha(path)}


def load_manifest(path: Path, root: Path) -> dict:
    data = load_json_object(path)
    fields(data, {'schema', 'series_id', 'requested_episodes', 'requirements', 'episodes'}, {'target_blog'}, 'series')
    if data['schema'] != 'naver-series/v1':
        raise BuildError('unsupported series schema', 'INVALID_CONTRACT')
    safe_segment(data['series_id'], 'series id')
    if data.get('target_blog') is not None:
        safe_segment(data['target_blog'], 'target blog')
    requested = data['requested_episodes']
    if not isinstance(requested, list) or not requested:
        raise BuildError('requested_episodes must be a nonempty array', 'INVALID_EPISODES')
    for ep in requested:
        require_int(ep, 'requested episode', minimum=1)
    if len(set(requested)) != len(requested):
        raise BuildError('duplicate requested episode', 'DUPLICATE_EPISODE')
    req = fields(data['requirements'], set(), {'images_per_episode', 'tag_line_max_chars'}, 'requirements')
    if 'images_per_episode' in req:
        require_int(req['images_per_episode'], 'images_per_episode')
    limit = require_int(req.get('tag_line_max_chars', 100), 'tag_line_max_chars')
    if limit > 100:
        raise BuildError('tag_line_max_chars may tighten but not exceed 100', 'INVALID_CONTRACT')
    if not isinstance(data['episodes'], list):
        raise BuildError('episodes must be an array', 'INVALID_EPISODES')
    seen = set(); articles = set()
    entries = []
    for entry in data['episodes']:
        fields(entry, {'episode', 'article', 'editorial', 'review'}, {'image_slots'}, 'episode entry')
        ep = require_int(entry['episode'], 'episode', minimum=1)
        if ep in seen:
            raise BuildError('duplicate episode entry', 'DUPLICATE_EPISODE')
        seen.add(ep)
        normalized = {'episode': ep}
        for key in ('article', 'editorial', 'review', 'image_slots'):
            if key in entry:
                normalized[key] = input_path(entry[key], path.parent, root)
        if normalized['article'] in articles or len(set(v for k, v in normalized.items() if k != 'episode')) != len(normalized) - 1:
            raise BuildError('article or sidecar path collision', 'EPISODE_IDENTITY_CONFLICT')
        articles.add(normalized['article'])
        entries.append(normalized)
    return {**data, 'requested_episodes': sorted(requested), 'original_request': list(requested),
            'requirements': {'images_per_episode': req.get('images_per_episode'), 'tag_line_max_chars': limit},
            'episodes': entries}


def check_review(review: dict | None, revision: str | None) -> tuple[str, list[str]]:
    if review is None:
        return 'review_pending', ['review file is missing']
    fields(review, {'schema', 'status', 'content_revision', 'checks', 'reviewed_by', 'reviewed_at'}, set(), 'review')
    if review['schema'] != 'naver-review/v1' or review['status'] not in ('pending', 'passed', 'needs_revision'):
        raise BuildError('invalid review schema/status', 'INVALID_REVIEW')
    if review['content_revision'] is not None and (not isinstance(review['content_revision'], str) or not SHA.fullmatch(review['content_revision'])):
        raise BuildError('review revision must be null or SHA-256', 'INVALID_REVIEW')
    checks = review['checks']; seen = set()
    if not isinstance(checks, list):
        raise BuildError('review checks must be an array', 'INVALID_REVIEW')
    for check in checks:
        fields(check, {'id', 'status', 'evidence'}, set(), 'review check')
        name = require_text(check['id'], 'check id')
        if name in seen or check['status'] not in ('pending', 'passed', 'needs_revision'):
            raise BuildError('duplicate/invalid review check', 'INVALID_REVIEW')
        seen.add(name)
        require_text(check['evidence'], 'review evidence', empty=True)
    if review['status'] == 'pending':
        return 'review_pending', ['content review has not passed']
    if review['content_revision'] != revision or revision is None:
        return 'stale_review', ['review does not match prepared content revision']
    if review['status'] == 'needs_revision':
        return 'needs_revision', ['reviewer requested revision; do not rewrite automatically']
    require_text(review['reviewed_by'], 'reviewed_by')
    try:
        if not isinstance(review['reviewed_at'], str) or datetime.fromisoformat(review['reviewed_at']).tzinfo is None:
            raise ValueError('timezone required')
    except ValueError as exc:
        raise BuildError('passed review needs a timezone-aware reviewed_at', 'INVALID_REVIEW') from exc
    if not REVIEW_CHECKS.issubset(seen) or any(c['status'] != 'passed' or not c['evidence'].strip() for c in checks):
        raise BuildError('passed review requires all quality checks and nonempty evidence', 'INVALID_REVIEW')
    return 'ready', []


def compose(source: Path, slots: Path, root: Path) -> str:
    helper = SKILLS.parent / 'scripts/insert_article_images.py'
    if not helper.is_file():
        raise BuildError('image slots require repository scripts/insert_article_images.py; no auto-install', 'DEPENDENCY_MISSING')
    # Import the repository helper, not a second Markdown/image-slot parser.
    sys.path.insert(0, str(helper.parent))
    from insert_article_images import compose_article_text, CompositionError
    try:
        return compose_article_text(source, slots, root=root, absolute_image_paths=True)[0]
    except CompositionError as exc:
        raise BuildError(str(exc), 'ASSETS_PENDING') from exc


def verify_sources(records: list[dict], root: Path) -> None:
    for record in records:
        path = input_path(record['path'], root, root)
        if record['sha256'] is None:
            if path.exists():
                raise BuildError('previously missing sidecar appeared: ' + path.name, 'SOURCE_CHANGED')
            continue
        if not path.is_file() or sha(path) != record['sha256']:
            raise BuildError('source or sidecar changed: ' + path.name, 'SOURCE_CHANGED')


def prepare(manifest: Path, input_root: Path, output_root: Path, run_id: str, *, check: bool = False, reuse: bool = False) -> dict:
    root = Path(input_root).expanduser().resolve()
    if not root.is_dir():
        raise BuildError('input root must exist', 'UNSAFE_PATH')
    path = input_path(str(manifest), Path.cwd(), root)
    destination = safe_run_directory(output_root, run_id)
    manifest_record = source_record(path)
    data = load_manifest(path, root)
    for dependency in (SKILLS / 'seo-series-writer/SKILL.md', DRAFTER / 'SKILL.md'):
        if not dependency.is_file():
            raise BuildError('required sibling skill missing: ' + str(dependency), 'DEPENDENCY_MISSING')
    entries = {e['episode']: e for e in data['episodes']}
    artifacts = {}; results = []; all_sources = [manifest_record]; all_assets = []
    for ep in data['requested_episodes']:
        result = {'episode': ep, 'status': 'missing', 'content_revision': None, 'errors': [], 'error_codes': []}
        results.append(result)
        if ep not in entries:
            result.update(errors=['requested episode is missing'], error_codes=['MISSING_EPISODE'])
            continue
        entry = entries[ep]; source = entry['article']; folder = f'episode-{ep:02d}'
        try:
            records = [source_record(p) if p.is_file() else {'path': str(p), 'sha256': None}
                       for k, p in entry.items() if k != 'episode']
            load_json_object(entry['editorial'])  # Explicit separate data; never merged into body.
            composed = compose(source, entry['image_slots'], root) if 'image_slots' in entry else None
            post, warnings = build_post(source, root, markdown_text=composed)
            if post['episode'] not in (None, ep):
                raise BuildError('manifest and article episode disagree', 'EPISODE_IDENTITY_CONFLICT')
            post['episode'] = ep
            preflight = preflight_report(post, source, warnings, expected_images=data['requirements']['images_per_episode'], project_root=root)
            if preflight['tag_string_length'] > data['requirements']['tag_line_max_chars']:
                preflight['errors'].append('configured tag limit exceeded')
                preflight['error_codes'].append('TAG_LENGTH_EXCEEDED')
                preflight['status'] = 'failed'
            revision = preflight['content_revision']
            # Retain canonical candidates even when review is missing/stale/invalid.
            artifacts[f'{folder}/naver-post.json'] = encoded(post)
            artifacts[f'{folder}/asset-integrity.json'] = encoded({'schema': 'naver-assets/v1', 'assets': preflight['asset_integrity']})
            artifacts[f'{folder}/editorial.json'] = entry['editorial'].read_text(encoding='utf-8')
            if composed is not None:
                artifacts[f'{folder}/article-with-images.md'] = composed
            result.update(content_revision=revision, image_count=preflight['image_count'], tag_string_length=preflight['tag_string_length'],
                          source_records=records, post=f'{folder}/naver-post.json', preflight=f'{folder}/preflight-report.json')
            try:
                review = load_json_object(entry['review']) if entry['review'].is_file() else None
                state, reasons = check_review(review, revision)
                if review is not None:
                    artifacts[f'{folder}/review.json'] = encoded(review)
                if state != 'ready':
                    artifacts[f'{folder}/review-template.json'] = encoded({'schema': 'naver-review/v1', 'status': 'pending',
                        'content_revision': revision, 'checks': [{'id': name, 'status': 'pending', 'evidence': ''} for name in sorted(REVIEW_CHECKS)],
                        'reviewed_by': None, 'reviewed_at': None})
            except (BuildError, OSError, UnicodeError) as exc:
                state, reasons = 'invalid_review', [str(exc)]
            preflight.update(content_review=state, review_errors=reasons)
            if preflight['errors']:
                state = 'assets_pending' if any('IMAGE' in c or c.startswith('ASSET') for c in preflight['error_codes']) else 'preflight_failed'
            result.update(status=state, errors=preflight['errors'] + reasons, error_codes=preflight['error_codes'])
            artifacts[f'{folder}/preflight-report.json'] = encoded(preflight)
            all_sources.extend(records); all_assets.extend(preflight['asset_integrity'])
        except (BuildError, OSError, UnicodeError) as exc:
            code = getattr(exc, 'code', 'INPUT_READ_ERROR')
            result.update(status='assets_pending' if code.startswith('ASSET') else 'preflight_failed', errors=[str(exc)], error_codes=[code])
    ready = all(e['status'] == 'ready' for e in results)
    report = {'schema': 'naver-series-prepared/v1', 'run_id': run_id, 'series_id': data['series_id'],
              'input_root': str(root), 'manifest_record': manifest_record, 'target_blog': data.get('target_blog'),
              'requested_episodes': data['requested_episodes'], 'original_request': data['original_request'],
              'ignored_episodes': sorted(set(entries) - set(data['requested_episodes'])), 'requirements': data['requirements'],
              'status': 'ready' if ready else 'blocked', 'queue': data['requested_episodes'] if ready else [],
              'candidate_queue': [e['episode'] for e in results if e['content_revision']],
              'ui_executable': False, 'ui_authorized': False, 'ui_verification': 'not_performed',
              'episodes': results, 'totals': {'requested': len(results), 'ready': sum(e['status'] == 'ready' for e in results),
              'images': sum(e.get('image_count', 0) for e in results), 'missing': sum(e['status'] == 'missing' for e in results)}}
    # Catch concurrent input/asset changes before publishing a new preparation snapshot.
    verify_sources(all_sources, root)
    for asset in all_assets:
        verify_asset(asset, root)
    artifacts['series-report.json'] = encoded(report)
    artifacts['snapshot.json'] = encoded({'schema': 'naver-series-snapshot/v1',
        'files': {name: hashlib.sha256(value.encode()).hexdigest() for name, value in sorted(artifacts.items())}})
    if ready:
        artifacts['complete.json'] = encoded({'schema': 'naver-series-ready/v1', 'snapshot_sha256': hashlib.sha256(artifacts['snapshot.json'].encode()).hexdigest()})
    if not check:
        write_prepared_run(destination, artifacts, reuse=reuse)
    return report


def read_snapshot(directory: Path) -> dict:
    raw = Path(directory).expanduser()
    if raw.is_symlink() or '..' in raw.parts:
        raise BuildError('unsafe snapshot path', 'UNSAFE_PATH')
    directory = raw.resolve()
    snapshot = load_json_object(directory / 'snapshot.json')
    fields(snapshot, {'schema', 'files'}, set(), 'snapshot')
    if snapshot['schema'] != 'naver-series-snapshot/v1' or not isinstance(snapshot['files'], dict) or not snapshot['files']:
        raise BuildError('invalid snapshot', 'CORRUPT_SNAPSHOT')
    files = snapshot['files']
    actual = {str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file() or p.is_symlink()}
    for name, digest in files.items():
        if not isinstance(name, str) or Path(name).is_absolute() or '..' in Path(name).parts or not isinstance(digest, str) or not SHA.fullmatch(digest):
            raise BuildError('unsafe snapshot entry', 'CORRUPT_SNAPSHOT')
        file = directory / name
        if any(p.is_symlink() for p in (file, *file.parents)) or not file.is_file() or sha(file) != digest:
            raise BuildError('snapshot file changed or missing', 'CORRUPT_SNAPSHOT')
    report = load_json_object(directory / 'series-report.json')
    if report.get('schema') != 'naver-series-prepared/v1' or 'series-report.json' not in files:
        raise BuildError('missing or unsupported prepared report', 'CORRUPT_SNAPSHOT')
    requested = report.get('requested_episodes')
    entries = report.get('episodes')
    if (not isinstance(requested, list) or not requested or any(type(ep) is not int or ep < 1 for ep in requested)
            or sorted(set(requested)) != requested or not isinstance(entries, list)
            or any(not isinstance(e, dict) or type(e.get('episode')) is not int for e in entries)
            or [e['episode'] for e in entries] != requested):
        raise BuildError('requested/observed episode sets disagree', 'CORRUPT_SNAPSHOT')
    all_ready = all(e.get('status') == 'ready' for e in entries)
    totals = {'requested': len(entries), 'ready': sum(e.get('status') == 'ready' for e in entries),
              'images': sum(e.get('image_count', 0) for e in entries), 'missing': sum(e.get('status') == 'missing' for e in entries)}
    if (report.get('status') != ('ready' if all_ready else 'blocked') or report.get('queue') != (requested if all_ready else [])
            or report.get('totals') != totals or report.get('ui_authorized') is not False or report.get('ui_executable') is not False):
        raise BuildError('preparation summary/authorization disagrees with episodes', 'CORRUPT_SNAPSHOT')
    ready = report.get('status') == 'ready'
    expected = set(files) | {'snapshot.json'} | ({'complete.json'} if ready else set())
    if actual != expected:
        raise BuildError('snapshot has missing/extra files', 'CORRUPT_SNAPSHOT')
    if ready:
        marker = load_json_object(directory / 'complete.json')
        if marker != {'schema': 'naver-series-ready/v1', 'snapshot_sha256': sha(directory / 'snapshot.json')}:
            raise BuildError('ready marker mismatch', 'CORRUPT_SNAPSHOT')
    return report


def status(run_directory: Path, *, execution_root: Path | None = None, target_blog: str | None = None, environment: str = 'live') -> dict:
    report = read_snapshot(run_directory)
    root = Path(report['input_root']); rows = []; issues = []
    blog = target_blog if target_blog is not None else report.get('target_blog')
    if blog is not None:
        safe_segment(blog, 'target blog')
    if target_blog is not None and report.get('target_blog') not in (None, target_blog):
        raise BuildError('target blog conflicts with prepared package', 'TARGET_CONFLICT')
    safe_segment(report['series_id'], 'series id')
    store = ExecutionStore(execution_root, environment=environment) if execution_root is not None else None
    try:
        verify_sources([report['manifest_record']], root)
    except (BuildError, OSError) as exc:
        issues.append(str(exc))
    for entry in report['episodes']:
        row = {'episode': entry['episode'], 'preparation': entry['status'], 'execution': None, 'issues': []}
        rows.append(row)
        if not entry.get('content_revision'):
            continue
        try:
            verify_sources(entry['source_records'], root)
            folder = Path(run_directory) / f"episode-{entry['episode']:02d}"
            post = load_json_object(folder / 'naver-post.json'); validate_post(post)
            assets = load_json_object(folder / 'asset-integrity.json')['assets']
            for asset in assets:
                verify_asset(asset, root)
            if post['episode'] != entry['episode'] or content_revision(post, assets) != entry['content_revision']:
                raise BuildError('canonical identity/revision mismatch', 'CORRUPT_SNAPSHOT')
            if entry['status'] == 'ready' and check_review(load_json_object(folder / 'review.json'), entry['content_revision'])[0] != 'ready':
                raise BuildError('review no longer ready', 'INVALID_REVIEW')
            if store is not None and blog is not None:
                key = ExecutionKey(blog, report['series_id'], entry['episode'], entry['content_revision'])
                row['execution'] = store.status(key)
        except (BuildError, OSError, ValueError, KeyError) as exc:
            row['issues'].append(str(exc))
    valid = not issues and not any(r['issues'] for r in rows)
    complete = valid and report['status'] == 'ready' and bool(rows) and all(r['execution'] is not None and r['execution']['state'] == 'blank_verified' and r['execution']['resume_decision'] == 'skip' for r in rows)
    remaining = [r for r in rows if r['execution'] is None or r['execution']['resume_decision'] != 'skip']
    eligible = valid and report['status'] == 'ready' and store is not None and blog is not None
    conflict = any(r['execution'] and r['execution']['resume_decision'] == 'revision_conflict' for r in rows)
    next_row = remaining[0] if remaining and eligible and not conflict else None
    queue = [r['episode'] for r in remaining] if eligible and not conflict and all(r['execution']['resume_decision'] == 'start' for r in remaining) else []
    return {'schema': 'naver-series-status/v1', 'series_id': report['series_id'], 'environment': environment,
            'preparation': report['status'], 'integrity': 'passed' if valid else 'failed', 'target_blog': blog,
            'requested_episodes': report['requested_episodes'], 'episodes': rows, 'issues': issues,
            'execution_complete': complete, 'live_complete': complete and environment == 'live',
            'prepared_queue': report['queue'] if valid else [], 'queue': queue,
            'remaining_episodes': [r['episode'] for r in remaining],
            'next_episode': next_row['episode'] if next_row else None,
            'next_action': next_row['execution']['resume_decision'] if next_row else ('complete' if complete else 'not_eligible'),
            'ui_authorized': False, 'ui_observed_now': False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    prepare_parser = sub.add_parser('prepare')
    prepare_parser.add_argument('--manifest', type=Path, required=True)
    prepare_parser.add_argument('--input-root', type=Path, required=True)
    prepare_parser.add_argument('--output-root', type=Path, required=True)
    prepare_parser.add_argument('--run-id', required=True)
    prepare_parser.add_argument('--check', action='store_true', help='validate without writes')
    prepare_parser.add_argument('--reuse', action='store_true', help='reuse exact immutable preparation only; never resume UI')
    status_parser = sub.add_parser('status')
    status_parser.add_argument('--run-directory', type=Path, required=True)
    status_parser.add_argument('--execution-root', type=Path)
    status_parser.add_argument('--target-blog')
    status_parser.add_argument('--environment', choices=('live', 'simulation'), default='live')
    args = parser.parse_args(argv)
    try:
        if args.mode == 'prepare':
            result = prepare(args.manifest, args.input_root, args.output_root, args.run_id, check=args.check, reuse=args.reuse)
            code = 0 if result['status'] == 'ready' else 1
        else:
            result = status(args.run_directory, execution_root=args.execution_root, target_blog=args.target_blog, environment=args.environment)
            code = 0 if result['integrity'] == 'passed' else 1
        print(encoded(result), end='')
        return code
    except (BuildError, OSError, UnicodeError, KeyError, TypeError, ValueError) as exc:
        print(encoded({'status': 'error', 'error_code': getattr(exc, 'code', 'INPUT_READ_ERROR'), 'error': str(exc)}), file=sys.stderr, end='')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
