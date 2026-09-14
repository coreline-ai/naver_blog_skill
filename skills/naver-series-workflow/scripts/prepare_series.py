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
from content_metrics import body_metrics

REVIEW_CHECKS = {
    'question_resolution',
    'practical_specificity',
    'factuality',
    'source_integrity',
    'originality',
    'title_body_match',
    'image_relevance',
    'editorial_boundary',
}
V2_REVIEW_CHECKS = REVIEW_CHECKS | {
    'style_fit',
    'limitations',
    'claim_source_map',
    'experience_integrity',
    'cross_episode_uniqueness',
}
WRITING_STYLES = {'expert', 'story', 'review', 'friendly', 'troubleshooting', 'comparison'}
PROFILE_REVIEW_CHECKS = {
    'expert': 'expert_information_assets',
    'story': 'story_arc_integrity',
    'review': 'review_evidence_integrity',
    'friendly': 'beginner_clarity',
    'troubleshooting': 'diagnostic_path',
    'comparison': 'symmetric_decision_criteria',
}
STYLE_IMAGE_TARGETS = {
    'expert': 5,
    'story': 4,
    'review': 5,
    'friendly': 3,
    'troubleshooting': 4,
    'comparison': 4,
}
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
    if data['schema'] not in ('naver-series/v1', 'naver-series/v2'):
        raise BuildError('unsupported series schema', 'INVALID_CONTRACT')
    series_schema = data['schema']
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
    if series_schema == 'naver-series/v1':
        allowed_requirements = {'visual_mode', 'images_per_episode', 'tag_line_max_chars'}
    else:
        allowed_requirements = {
            'content_mode', 'primary_style', 'secondary_style', 'min_body_chars',
            'visual_mode', 'min_images_per_episode', 'target_images_per_episode',
            'tag_line_max_chars',
        }
    req = fields(data['requirements'], set(), allowed_requirements, 'requirements')
    visual_mode = req.get('visual_mode')
    if visual_mode is not None and visual_mode not in ('required', 'optional', 'none'):
        raise BuildError('visual_mode must be required, optional, or none', 'INVALID_CONTRACT')
    if series_schema == 'naver-series/v1':
        if 'images_per_episode' in req:
            require_int(req['images_per_episode'], 'images_per_episode')
            if visual_mode is None:
                visual_mode = 'required'
        if visual_mode is None:
            visual_mode = 'optional'
        if visual_mode == 'required' and ('images_per_episode' not in req or req['images_per_episode'] < 1):
            raise BuildError('required visuals need a positive images_per_episode', 'INVALID_CONTRACT')
        if visual_mode == 'none' and req.get('images_per_episode') not in (None, 0):
            raise BuildError('visual_mode none conflicts with images_per_episode', 'INVALID_CONTRACT')
        normalized_requirements = {
            'visual_mode': visual_mode,
            'images_per_episode': 0 if visual_mode == 'none' else req.get('images_per_episode'),
        }
    else:
        content_mode = req.get('content_mode', 'full_article')
        if content_mode != 'full_article':
            raise BuildError('v2 content_mode must be full_article', 'INVALID_CONTRACT')
        primary = req.get('primary_style', 'expert')
        secondary = req.get('secondary_style', 'friendly')
        if primary not in WRITING_STYLES or secondary not in WRITING_STYLES or primary == secondary:
            raise BuildError('v2 requires two distinct supported writing styles', 'INVALID_CONTRACT')
        min_body = require_int(req.get('min_body_chars', 3000), 'min_body_chars', minimum=3000)
        visual_mode = visual_mode or 'optional'
        if visual_mode == 'required':
            minimum_images = require_int(req.get('min_images_per_episode', 3), 'min_images_per_episode', minimum=3)
            target_images = require_int(
                req.get('target_images_per_episode', max(minimum_images, STYLE_IMAGE_TARGETS[primary])),
                'target_images_per_episode', minimum=minimum_images,
            )
        elif visual_mode == 'none':
            if req.get('min_images_per_episode') not in (None, 0) or req.get('target_images_per_episode') not in (None, 0):
                raise BuildError('visual_mode none conflicts with image requirements', 'INVALID_CONTRACT')
            minimum_images = target_images = 0
        else:
            if 'min_images_per_episode' in req or 'target_images_per_episode' in req:
                raise BuildError('optional visuals cannot declare required image counts', 'INVALID_CONTRACT')
            minimum_images = 0
            target_images = None
        normalized_requirements = {
            'content_mode': content_mode,
            'primary_style': primary,
            'secondary_style': secondary,
            'min_body_chars': min_body,
            'visual_mode': visual_mode,
            'min_images_per_episode': minimum_images,
            'target_images_per_episode': target_images,
        }
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
            'requirements': {**normalized_requirements, 'tag_line_max_chars': limit},
            'episodes': entries}


def required_review_checks(*, version: int, styles: set[str] | None = None) -> set[str]:
    if version == 1:
        return set(REVIEW_CHECKS)
    selected = styles or set()
    return set(V2_REVIEW_CHECKS) | {PROFILE_REVIEW_CHECKS[style] for style in selected}


def check_review(review: dict | None, revision: str | None, *, version: int = 1,
                 styles: set[str] | None = None) -> tuple[str, list[str]]:
    if review is None:
        return 'review_pending', ['review file is missing']
    fields(review, {'schema', 'status', 'content_revision', 'checks', 'reviewed_by', 'reviewed_at'}, set(), 'review')
    expected_schema = f'naver-review/v{version}'
    if review['schema'] != expected_schema or review['status'] not in ('pending', 'passed', 'needs_revision'):
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
        if version == 1:
            require_text(check['evidence'], 'review evidence', empty=True)
        else:
            evidence = check['evidence']
            if not isinstance(evidence, list):
                raise BuildError('v2 review evidence must be an array', 'INVALID_REVIEW')
            for item in evidence:
                fields(item, {'location', 'finding', 'source_refs'}, set(), 'review evidence item')
                location = require_text(item['location'], 'review evidence location')
                finding = require_text(item['finding'], 'review evidence finding')
                if len(location.strip()) < 3 or len(finding.strip()) < 12:
                    raise BuildError('v2 review evidence must identify a concrete location and finding', 'REVIEW_EVIDENCE_INSUFFICIENT')
                if not isinstance(item['source_refs'], list) or any(not isinstance(ref, str) or not ref.strip() for ref in item['source_refs']):
                    raise BuildError('source_refs must be an array of nonempty strings', 'INVALID_REVIEW')
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
    required_checks = required_review_checks(version=version, styles=styles)
    def evidence_present(check: dict) -> bool:
        return bool(check['evidence'].strip()) if version == 1 else bool(check['evidence'])
    if not required_checks.issubset(seen) or any(c['status'] != 'passed' or not evidence_present(c) for c in checks):
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


def validate_v2_editorial(editorial: dict, requirements: dict) -> None:
    """Require an honest experience basis when a profile implies first-hand material."""
    styles = {requirements['primary_style'], requirements['secondary_style']}
    if not styles.intersection({'story', 'review'}):
        return
    basis = editorial.get('experience_basis')
    if not isinstance(basis, dict) or set(basis) != {'type', 'evidence'}:
        raise BuildError('story/review profile needs structured experience_basis', 'EXPERIENCE_BASIS_MISSING')
    allowed = {'user_provided', 'verified_records', 'illustrative'}
    if basis.get('type') not in allowed or not isinstance(basis.get('evidence'), list):
        raise BuildError('invalid experience_basis', 'EXPERIENCE_BASIS_MISSING')
    if basis['type'] in {'user_provided', 'verified_records'} and (
        not basis['evidence'] or not all(isinstance(item, str) and item.strip() for item in basis['evidence'])
    ):
        raise BuildError('experience evidence must be nonempty strings', 'EXPERIENCE_BASIS_MISSING')
    if 'review' in styles and (basis['type'] == 'illustrative' or not basis['evidence']):
        raise BuildError('review profile requires user-provided or verified experience evidence', 'EXPERIENCE_BASIS_MISSING')


def image_slot_metadata(path: Path | None) -> tuple[list[str], list[str]]:
    if path is None:
        return [], []
    data = load_json_object(path)
    slots = data.get('slots')
    if not isinstance(slots, list):
        return [], []
    roles = [slot.get('role') for slot in slots if isinstance(slot, dict) and isinstance(slot.get('role'), str)]
    captions = [slot.get('caption') for slot in slots if isinstance(slot, dict) and isinstance(slot.get('caption'), str)]
    return roles, captions


def apply_v2_visual_checks(preflight: dict, roles: list[str], requirements: dict) -> dict:
    """Add complete-package image semantics without changing the shared drafter parser."""
    count = preflight['image_count']
    hashes = [asset['sha256'] for asset in preflight['asset_integrity']]
    unique_count = len(set(hashes))
    mode = requirements['visual_mode']
    minimum = requirements['min_images_per_episode']
    target = requirements['target_images_per_episode']
    errors: list[tuple[str, str]] = []
    if unique_count != len(hashes):
        errors.append(('image files with identical content cannot satisfy multiple slots', 'DUPLICATE_ASSET'))
    if mode == 'required':
        if count < minimum or unique_count < minimum:
            errors.append((f'required at least {minimum} approved unique images; found {unique_count}', 'VISUAL_MINIMUM_NOT_MET'))
        if roles.count('cover') != 1 or roles.count('inline') < 2 or not roles or roles[0] != 'cover':
            errors.append(('complete visual package needs first-slot cover and at least two inline images', 'INLINE_IMAGES_MISSING'))
    elif mode == 'none' and count:
        errors.append(('visual_mode none requires zero images', 'IMAGE_COUNT_MISMATCH'))
    for message, code in errors:
        if code not in preflight['error_codes']:
            preflight['errors'].append(message)
            preflight['error_codes'].append(code)
    if errors:
        preflight['status'] = 'failed'
    return {
        'visual_minimum_met': mode != 'required' or (count >= minimum and unique_count >= minimum),
        'visual_target_met': target is None or unique_count >= target,
        'unique_image_count': unique_count,
        'cover_image_count': roles.count('cover'),
        'inline_image_count': roles.count('inline'),
    }


def review_template(revision: str | None, *, version: int, styles: set[str] | None = None) -> dict:
    checks = required_review_checks(version=version, styles=styles)
    empty_evidence: str | list = '' if version == 1 else []
    return {
        'schema': f'naver-review/v{version}',
        'status': 'pending',
        'content_revision': revision,
        'checks': [{'id': name, 'status': 'pending', 'evidence': empty_evidence} for name in sorted(checks)],
        'reviewed_by': None,
        'reviewed_at': None,
    }


def v2_review_signature(review: dict | None) -> str | None:
    if not review or review.get('schema') != 'naver-review/v2' or review.get('status') != 'passed':
        return None
    evidence = sorted(
        ({'id': item.get('id'), 'evidence': item.get('evidence')} for item in review.get('checks', [])),
        key=lambda item: str(item['id']),
    )
    return hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


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
    contract_version = 2 if data['schema'] == 'naver-series/v2' else 1
    review_styles = ({data['requirements']['primary_style'], data['requirements']['secondary_style']}
                     if contract_version == 2 else None)
    for dependency in (SKILLS / 'seo-series-writer/SKILL.md', DRAFTER / 'SKILL.md'):
        if not dependency.is_file():
            raise BuildError('required sibling skill missing: ' + str(dependency), 'DEPENDENCY_MISSING')
    entries = {e['episode']: e for e in data['episodes']}
    artifacts = {}; results = []; all_sources = [manifest_record]; all_assets = []
    review_signatures: dict[str, list[int]] = {}
    for ep in data['requested_episodes']:
        result = {'episode': ep, 'status': 'missing', 'content_revision': None, 'errors': [], 'error_codes': []}
        if contract_version == 2:
            result.update(structure_ready=False, length_ready=False, editorial_ready=False,
                          visual_ready=False, draft_input_ready=False)
        results.append(result)
        if ep not in entries:
            result.update(errors=['requested episode is missing'], error_codes=['MISSING_EPISODE'])
            continue
        entry = entries[ep]; source = entry['article']; folder = f'episode-{ep:02d}'
        try:
            records = [source_record(p) if p.is_file() else {'path': str(p), 'sha256': None}
                       for k, p in entry.items() if k != 'episode']
            editorial = load_json_object(entry['editorial'])  # Explicit separate data; never merged into body.
            if contract_version == 2:
                validate_v2_editorial(editorial, data['requirements'])
            composed = compose(source, entry['image_slots'], root) if 'image_slots' in entry else None
            post, warnings = build_post(source, root, markdown_text=composed)
            if post['episode'] not in (None, ep):
                raise BuildError('manifest and article episode disagree', 'EPISODE_IDENTITY_CONFLICT')
            post['episode'] = ep
            expected_images = data['requirements']['images_per_episode'] if contract_version == 1 else None
            preflight = preflight_report(post, source, warnings, expected_images=expected_images, project_root=root)
            roles, captions = image_slot_metadata(entry.get('image_slots'))
            metrics = body_metrics(post, excluded_texts=captions)
            if contract_version == 2:
                if metrics['body_char_count'] < data['requirements']['min_body_chars']:
                    preflight['errors'].append(
                        f"public body requires at least {data['requirements']['min_body_chars']} characters; found {metrics['body_char_count']}"
                    )
                    preflight['error_codes'].append('CONTENT_TOO_SHORT')
                    preflight['status'] = 'failed'
                visual = apply_v2_visual_checks(preflight, roles, data['requirements'])
                preflight.update(content_metrics=metrics, visual_quality=visual)
            if preflight['tag_string_length'] > data['requirements']['tag_line_max_chars']:
                preflight['errors'].append('configured tag limit exceeded')
                preflight['error_codes'].append('TAG_LENGTH_EXCEEDED')
                preflight['status'] = 'failed'
            revision = preflight['content_revision']
            # Retain canonical candidates even when review is missing/stale/invalid.
            artifacts[f'{folder}/naver-post.json'] = encoded(post)
            artifacts[f'{folder}/asset-integrity.json'] = encoded({'schema': 'naver-assets/v1', 'assets': preflight['asset_integrity']})
            artifacts[f'{folder}/editorial.json'] = entry['editorial'].read_text(encoding='utf-8')
            if contract_version == 2:
                artifacts[f'{folder}/content-metrics.json'] = encoded(metrics)
            if composed is not None:
                artifacts[f'{folder}/article-with-images.md'] = composed
            result.update(content_revision=revision, image_count=preflight['image_count'], tag_string_length=preflight['tag_string_length'],
                          source_records=records, post=f'{folder}/naver-post.json', preflight=f'{folder}/preflight-report.json')
            try:
                review = load_json_object(entry['review']) if entry['review'].is_file() else None
                state, reasons = check_review(review, revision, version=contract_version, styles=review_styles)
                if review is not None:
                    artifacts[f'{folder}/review.json'] = encoded(review)
                signature = v2_review_signature(review)
                if signature and state == 'ready':
                    review_signatures.setdefault(signature, []).append(ep)
                if state != 'ready':
                    artifacts[f'{folder}/review-template.json'] = encoded(
                        review_template(revision, version=contract_version, styles=review_styles)
                    )
            except (BuildError, OSError, UnicodeError) as exc:
                state, reasons = 'invalid_review', [str(exc)]
            review_state = state
            preflight.update(content_review=state, review_errors=reasons)
            if preflight['errors']:
                image_error = any('IMAGE' in c or c.startswith('ASSET') or c in {'VISUAL_MINIMUM_NOT_MET', 'INLINE_IMAGES_MISSING', 'DUPLICATE_ASSET'}
                                  for c in preflight['error_codes'])
                length_error = 'CONTENT_TOO_SHORT' in preflight['error_codes']
                state = 'assets_pending' if image_error else ('content_too_short' if length_error else 'preflight_failed')
            result.update(status=state, errors=preflight['errors'] + reasons, error_codes=preflight['error_codes'])
            if contract_version == 2:
                structure_ready = not any(code not in {'CONTENT_TOO_SHORT', 'VISUAL_MINIMUM_NOT_MET', 'INLINE_IMAGES_MISSING', 'DUPLICATE_ASSET'}
                                          for code in preflight['error_codes'])
                length_ready = metrics['body_char_count'] >= data['requirements']['min_body_chars']
                visual_ready = preflight['visual_quality']['visual_minimum_met'] and not any(
                    code in {'IMAGE_COUNT_MISMATCH', 'VISUAL_MINIMUM_NOT_MET', 'INLINE_IMAGES_MISSING', 'DUPLICATE_ASSET'} or
                    code.startswith('ASSET') or 'IMAGE' in code for code in preflight['error_codes']
                )
                editorial_ready = review_state == 'ready'
                result.update(
                    body_char_count=metrics['body_char_count'],
                    structure_ready=structure_ready,
                    length_ready=length_ready,
                    editorial_ready=editorial_ready,
                    visual_ready=visual_ready,
                    visual_minimum_met=preflight['visual_quality']['visual_minimum_met'],
                    visual_target_met=preflight['visual_quality']['visual_target_met'],
                    draft_input_ready=structure_ready and length_ready and editorial_ready and visual_ready,
                )
            artifacts[f'{folder}/preflight-report.json'] = encoded(preflight)
            all_sources.extend(records); all_assets.extend(preflight['asset_integrity'])
        except (BuildError, OSError, UnicodeError) as exc:
            code = getattr(exc, 'code', 'INPUT_READ_ERROR')
            result.update(status='assets_pending' if code.startswith('ASSET') else 'preflight_failed', errors=[str(exc)], error_codes=[code])
    if contract_version == 2:
        for signature, episodes in review_signatures.items():
            if len(episodes) < 2:
                continue
            for ep in episodes:
                result = next(item for item in results if item['episode'] == ep)
                result['status'] = 'invalid_review'
                result['editorial_ready'] = False
                result['draft_input_ready'] = False
                result['errors'].append('identical structured review evidence was reused across episodes')
                result['error_codes'].append('REVIEW_EVIDENCE_REUSED')
                name = f'episode-{ep:02d}/preflight-report.json'
                preflight = json.loads(artifacts[name])
                preflight['content_review'] = 'invalid_review'
                preflight['review_errors'].append('identical structured review evidence was reused across episodes')
                artifacts[name] = encoded(preflight)
                artifacts[f'episode-{ep:02d}/review-template.json'] = encoded(
                    review_template(result['content_revision'], version=2, styles=review_styles)
                )
    ready = all(e['status'] == 'ready' and (contract_version == 1 or e['draft_input_ready']) for e in results)
    report_schema = f'naver-series-prepared/v{contract_version}'
    report = {'schema': report_schema, 'run_id': run_id, 'series_id': data['series_id'],
              'input_root': str(root), 'manifest_record': manifest_record, 'target_blog': data.get('target_blog'),
              'requested_episodes': data['requested_episodes'], 'original_request': data['original_request'],
              'ignored_episodes': sorted(set(entries) - set(data['requested_episodes'])), 'requirements': data['requirements'],
              'status': 'ready' if ready else 'blocked', 'queue': data['requested_episodes'] if ready else [],
              'candidate_queue': [e['episode'] for e in results if e['content_revision']],
              'ui_executable': False, 'ui_authorized': False, 'ui_verification': 'not_performed',
              'episodes': results, 'totals': {'requested': len(results), 'ready': sum(e['status'] == 'ready' for e in results),
              'images': sum(e.get('image_count', 0) for e in results), 'missing': sum(e['status'] == 'missing' for e in results)}}
    if contract_version == 1:
        report['quality_contract'] = 'legacy_ungraded'
    else:
        report['quality_contract'] = 'full-article-v2'
    # Catch concurrent input/asset changes before publishing a new preparation snapshot.
    verify_sources(all_sources, root)
    for asset in all_assets:
        verify_asset(asset, root)
    artifacts['series-report.json'] = encoded(report)
    artifacts['snapshot.json'] = encoded({'schema': f'naver-series-snapshot/v{contract_version}',
        'files': {name: hashlib.sha256(value.encode()).hexdigest() for name, value in sorted(artifacts.items())}})
    if ready:
        artifacts['complete.json'] = encoded({'schema': f'naver-series-ready/v{contract_version}', 'snapshot_sha256': hashlib.sha256(artifacts['snapshot.json'].encode()).hexdigest()})
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
    if snapshot['schema'] not in ('naver-series-snapshot/v1', 'naver-series-snapshot/v2') or not isinstance(snapshot['files'], dict) or not snapshot['files']:
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
    if report.get('schema') not in ('naver-series-prepared/v1', 'naver-series-prepared/v2') or 'series-report.json' not in files:
        raise BuildError('missing or unsupported prepared report', 'CORRUPT_SNAPSHOT')
    version = 2 if report['schema'].endswith('/v2') else 1
    if snapshot['schema'] != f'naver-series-snapshot/v{version}':
        raise BuildError('snapshot/report version mismatch', 'CORRUPT_SNAPSHOT')
    requested = report.get('requested_episodes')
    entries = report.get('episodes')
    if (not isinstance(requested, list) or not requested or any(type(ep) is not int or ep < 1 for ep in requested)
            or sorted(set(requested)) != requested or not isinstance(entries, list)
            or any(not isinstance(e, dict) or type(e.get('episode')) is not int for e in entries)
            or [e['episode'] for e in entries] != requested):
        raise BuildError('requested/observed episode sets disagree', 'CORRUPT_SNAPSHOT')
    all_ready = all(e.get('status') == 'ready' and (version == 1 or e.get('draft_input_ready') is True) for e in entries)
    if version == 2:
        requirements = report.get('requirements')
        if not isinstance(requirements, dict) or report.get('quality_contract') != 'full-article-v2':
            raise BuildError('missing v2 quality contract', 'CORRUPT_SNAPSHOT')
        minimum_body = requirements.get('min_body_chars')
        if type(minimum_body) is not int or minimum_body < 3000:
            raise BuildError('invalid v2 body requirement', 'CORRUPT_SNAPSHOT')
        for entry in entries:
            flags = [entry.get(key) for key in ('structure_ready', 'length_ready', 'editorial_ready', 'visual_ready')]
            if any(type(flag) is not bool for flag in flags) or type(entry.get('draft_input_ready')) is not bool:
                raise BuildError('missing v2 readiness flags', 'CORRUPT_SNAPSHOT')
            body_count = entry.get('body_char_count')
            if entry.get('content_revision') is not None and (
                type(body_count) is not int or entry['length_ready'] != (body_count >= minimum_body)
            ):
                raise BuildError('v2 length summary mismatch', 'CORRUPT_SNAPSHOT')
            if entry['draft_input_ready'] != all(flags) or (entry.get('status') == 'ready') != entry['draft_input_ready']:
                raise BuildError('v2 readiness summary mismatch', 'CORRUPT_SNAPSHOT')
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
        if marker != {'schema': f'naver-series-ready/v{version}', 'snapshot_sha256': sha(directory / 'snapshot.json')}:
            raise BuildError('ready marker mismatch', 'CORRUPT_SNAPSHOT')
    return report


def status(run_directory: Path, *, execution_root: Path | None = None, target_blog: str | None = None, environment: str = 'live') -> dict:
    report = read_snapshot(run_directory)
    contract_version = 2 if report['schema'].endswith('/v2') else 1
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
        if contract_version == 2:
            for key in ('structure_ready', 'length_ready', 'editorial_ready', 'visual_ready',
                        'draft_input_ready', 'body_char_count', 'visual_minimum_met', 'visual_target_met'):
                row[key] = entry.get(key)
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
            styles = ({report['requirements']['primary_style'], report['requirements']['secondary_style']}
                      if contract_version == 2 else None)
            if entry['status'] == 'ready' and check_review(
                load_json_object(folder / 'review.json'), entry['content_revision'],
                version=contract_version, styles=styles,
            )[0] != 'ready':
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
    return {'schema': f'naver-series-status/v{contract_version}', 'series_id': report['series_id'], 'environment': environment,
            'quality_contract': report.get('quality_contract'),
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
