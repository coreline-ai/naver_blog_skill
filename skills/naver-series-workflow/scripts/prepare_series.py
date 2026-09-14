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


def compose(source: Path, slots: Path, root: Path) -> tuple[str, list[dict[str, str]]]:
    helper = SKILLS.parent / 'scripts/insert_article_images.py'
    if not helper.is_file():
        raise BuildError('image slots require repository scripts/insert_article_images.py; no auto-install', 'DEPENDENCY_MISSING')
    # Import the repository helper, not a second Markdown/image-slot parser.
    sys.path.insert(0, str(helper.parent))
    from insert_article_images import compose_article_data, CompositionError
    try:
        return compose_article_data(source, slots, root=root, absolute_image_paths=True)
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


def build_slot_bindings(post: dict, slots: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Bind validated composition slots to canonical image/caption block identities."""
    blocks = post['blocks']
    images = {block['path']: (index, block) for index, block in enumerate(blocks) if block['type'] == 'image'}
    bindings: list[dict[str, Any]] = []
    previous_index = -1
    for slot in slots:
        match = images.get(slot['path'])
        if match is None:
            raise BuildError('composed slot image is missing from canonical post', 'COMPOSITION_BINDING_INVALID')
        index, image = match
        if index <= previous_index:
            raise BuildError('canonical image order disagrees with slot order', 'COMPOSITION_BINDING_INVALID')
        previous_index = index
        caption_block_id = None
        if slot['caption']:
            if index + 1 >= len(blocks) or blocks[index + 1]['type'] != 'paragraph':
                raise BuildError('composed caption is not adjacent to its image', 'CAPTION_STRUCTURE_INVALID')
            caption_block_id = blocks[index + 1]['id']
        bindings.append({
            'id': slot['id'],
            'role': slot['role'],
            'path': slot['path'],
            'image_block_id': image['id'],
            'image_block_index': index,
            'caption_block_id': caption_block_id,
        })
    return bindings


def validate_slot_bindings(post: dict, value: Any) -> list[dict[str, Any]]:
    """Validate stored derived bindings before using them for status recomputation."""
    if not isinstance(value, list):
        raise BuildError('slot_bindings must be an array', 'CORRUPT_SNAPSHOT')
    blocks = post['blocks']
    by_id = {block['id']: (index, block) for index, block in enumerate(blocks)}
    seen_slots: set[str] = set(); seen_images: set[str] = set(); seen_captions: set[str] = set()
    previous_index = -1; bindings: list[dict[str, Any]] = []
    for raw in value:
        fields(raw, {'id', 'role', 'path', 'image_block_id', 'image_block_index', 'caption_block_id'}, set(), 'slot binding')
        slot_id = require_text(raw['id'], 'slot binding id')
        role = require_text(raw['role'], 'slot binding role')
        path = require_text(raw['path'], 'slot binding path')
        image_block_id = require_text(raw['image_block_id'], 'slot image block id')
        image_index = require_int(raw['image_block_index'], 'slot image block index')
        caption_id = raw['caption_block_id']
        if role not in {'cover', 'inline'} or slot_id in seen_slots or image_block_id in seen_images:
            raise BuildError('duplicate or invalid slot binding', 'CORRUPT_SNAPSHOT')
        match = by_id.get(image_block_id)
        if match is None or match[0] != image_index or match[1]['type'] != 'image' or match[1]['path'] != path:
            raise BuildError('slot binding does not match canonical image', 'CORRUPT_SNAPSHOT')
        if image_index <= previous_index:
            raise BuildError('slot binding order is not canonical', 'CORRUPT_SNAPSHOT')
        if caption_id is not None:
            if not isinstance(caption_id, str) or not caption_id.strip() or caption_id in seen_captions:
                raise BuildError('invalid caption block binding', 'CORRUPT_SNAPSHOT')
            caption = by_id.get(caption_id)
            if caption is None or caption[0] != image_index + 1 or caption[1]['type'] != 'paragraph':
                raise BuildError('caption binding is not adjacent to its image', 'CORRUPT_SNAPSHOT')
            seen_captions.add(caption_id)
        seen_slots.add(slot_id); seen_images.add(image_block_id); previous_index = image_index
        bindings.append(dict(raw))
    return bindings


def evaluate_v2_visual(post: dict, assets: list[dict], bindings: list[dict[str, Any]], requirements: dict) -> tuple[dict, list[tuple[str, str]]]:
    """Return deterministic visual quality facts and their contract errors."""
    count = sum(block['type'] == 'image' for block in post['blocks'])
    hashes = [asset['sha256'] for asset in assets]
    unique_count = len(set(hashes))
    mode = requirements['visual_mode']
    minimum = requirements['min_images_per_episode']
    target = requirements['target_images_per_episode']
    roles = [binding['role'] for binding in bindings]
    errors: list[tuple[str, str]] = []
    if unique_count != len(hashes):
        errors.append(('image files with identical content cannot satisfy multiple slots', 'DUPLICATE_ASSET'))
    role_contract_valid = roles.count('cover') == 1 and roles.count('inline') >= 2 and bool(roles) and roles[0] == 'cover'
    cover_position_valid = mode != 'required'
    if mode == 'required':
        if count < minimum or unique_count < minimum:
            errors.append((f'required at least {minimum} approved unique images; found {unique_count}', 'VISUAL_MINIMUM_NOT_MET'))
        if not role_contract_valid:
            errors.append(('complete visual package needs first-slot cover and at least two inline images', 'INLINE_IMAGES_MISSING'))
        else:
            first = post['blocks'][0] if post['blocks'] else None
            cover_position_valid = bool(
                first and first['type'] == 'image' and first['id'] == bindings[0]['image_block_id']
            )
            if not cover_position_valid:
                errors.append(('cover image must be the first content block immediately after H1', 'COVER_POSITION_INVALID'))
    elif mode == 'none' and count:
        errors.append(('visual_mode none requires zero images', 'IMAGE_COUNT_MISMATCH'))
    visual = {
        'visual_minimum_met': mode != 'required' or (count >= minimum and unique_count >= minimum),
        'visual_target_met': target is None or unique_count >= target,
        'unique_image_count': unique_count,
        'cover_image_count': roles.count('cover'),
        'inline_image_count': roles.count('inline'),
        'cover_position_valid': cover_position_valid,
        'slot_bindings': bindings,
    }
    return visual, errors


def add_preflight_errors(preflight: dict, errors: list[tuple[str, str]]) -> None:
    for message, code in errors:
        if code not in preflight['error_codes']:
            preflight['errors'].append(message)
            preflight['error_codes'].append(code)
    if errors:
        preflight['status'] = 'failed'


def is_v2_visual_error(code: str) -> bool:
    return (
        code in {'VISUAL_MINIMUM_NOT_MET', 'INLINE_IMAGES_MISSING', 'DUPLICATE_ASSET',
                 'COVER_POSITION_INVALID', 'IMAGE_COUNT_MISMATCH'}
        or code.startswith('ASSET') or 'IMAGE' in code
    )


def derive_v2_episode_state(preflight: dict, metrics: dict, requirements: dict,
                            review_state: str, review_errors: list[str]) -> dict[str, Any]:
    """Derive all v2 readiness fields from canonical diagnostics."""
    error_codes = list(preflight['error_codes'])
    visual_codes = {code for code in error_codes if is_v2_visual_error(code)}
    structure_ready = not any(code != 'CONTENT_TOO_SHORT' and code not in visual_codes for code in error_codes)
    length_ready = metrics['body_char_count'] >= requirements['min_body_chars']
    visual = preflight['visual_quality']
    visual_ready = visual['visual_minimum_met'] and not visual_codes
    editorial_ready = review_state == 'ready'
    draft_input_ready = structure_ready and length_ready and editorial_ready and visual_ready
    if preflight['errors']:
        state = 'assets_pending' if visual_codes else ('content_too_short' if 'CONTENT_TOO_SHORT' in error_codes else 'preflight_failed')
    else:
        state = review_state
    return {
        'status': state,
        'errors': list(preflight['errors']) + list(review_errors),
        'error_codes': error_codes + list(preflight.get('review_error_codes', [])),
        'body_char_count': metrics['body_char_count'],
        'structure_ready': structure_ready,
        'length_ready': length_ready,
        'editorial_ready': editorial_ready,
        'visual_ready': visual_ready,
        'visual_minimum_met': visual['visual_minimum_met'],
        'visual_target_met': visual['visual_target_met'],
        'draft_input_ready': draft_input_ready,
    }


def review_template(revision: str | None, *, version: int, styles: set[str] | None = None) -> dict:
    checks = required_review_checks(version=version, styles=styles)
    return {
        'schema': f'naver-review/v{version}',
        'status': 'pending',
        'content_revision': revision,
        'checks': [
            {'id': name, 'status': 'pending', 'evidence': '' if version == 1 else []}
            for name in sorted(checks)
        ],
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
            composed, slots = compose(source, entry['image_slots'], root) if 'image_slots' in entry else (None, [])
            post, warnings = build_post(source, root, markdown_text=composed)
            if post['episode'] not in (None, ep):
                raise BuildError('manifest and article episode disagree', 'EPISODE_IDENTITY_CONFLICT')
            post['episode'] = ep
            expected_images = data['requirements']['images_per_episode'] if contract_version == 1 else None
            preflight = preflight_report(post, source, warnings, expected_images=expected_images, project_root=root)
            if contract_version == 2:
                bindings = build_slot_bindings(post, slots)
                caption_ids = [binding['caption_block_id'] for binding in bindings if binding['caption_block_id']]
                metrics = body_metrics(post, excluded_block_ids=caption_ids)
                if metrics['body_char_count'] < data['requirements']['min_body_chars']:
                    preflight['errors'].append(
                        f"public body requires at least {data['requirements']['min_body_chars']} characters; found {metrics['body_char_count']}"
                    )
                    preflight['error_codes'].append('CONTENT_TOO_SHORT')
                    preflight['status'] = 'failed'
                visual, visual_errors = evaluate_v2_visual(
                    post, preflight['asset_integrity'], bindings, data['requirements']
                )
                add_preflight_errors(preflight, visual_errors)
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
            preflight.update(content_review=state, review_errors=reasons, review_error_codes=[])
            if contract_version == 2:
                result.update(derive_v2_episode_state(
                    preflight, metrics, data['requirements'], review_state, reasons
                ))
            else:
                if preflight['errors']:
                    state = 'assets_pending' if any('IMAGE' in c or c.startswith('ASSET') for c in preflight['error_codes']) else 'preflight_failed'
                result.update(status=state, errors=preflight['errors'] + reasons, error_codes=preflight['error_codes'])
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
                preflight.setdefault('review_error_codes', []).append('REVIEW_EVIDENCE_REUSED')
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


def validate_v2_snapshot_episode(directory: Path, entry: dict, requirements: dict) -> None:
    """Cross-check v2 report summaries against their canonical episode artifacts."""
    flags = ('structure_ready', 'length_ready', 'editorial_ready', 'visual_ready', 'draft_input_ready')
    if any(type(entry.get(key)) is not bool for key in flags):
        raise BuildError('missing v2 readiness flags', 'CORRUPT_SNAPSHOT')
    if not entry.get('post') or not entry.get('preflight'):
        if entry.get('content_revision') is not None or entry.get('status') == 'ready' or any(entry[key] for key in flags):
            raise BuildError('v2 episode summary lacks canonical artifacts', 'CORRUPT_SNAPSHOT')
        return

    folder = directory / f"episode-{entry['episode']:02d}"
    expected_post = f"episode-{entry['episode']:02d}/naver-post.json"
    expected_preflight = f"episode-{entry['episode']:02d}/preflight-report.json"
    if entry['post'] != expected_post or entry['preflight'] != expected_preflight:
        raise BuildError('v2 episode artifact paths disagree', 'CORRUPT_SNAPSHOT')
    post = load_json_object(folder / 'naver-post.json'); validate_post(post)
    asset_document = load_json_object(folder / 'asset-integrity.json')
    fields(asset_document, {'schema', 'assets'}, set(), 'asset integrity')
    if asset_document['schema'] != 'naver-assets/v1' or not isinstance(asset_document['assets'], list):
        raise BuildError('invalid asset integrity artifact', 'CORRUPT_SNAPSHOT')
    assets = asset_document['assets']
    metrics = load_json_object(folder / 'content-metrics.json')
    preflight = load_json_object(folder / 'preflight-report.json')
    if metrics.get('schema') != 'naver-content-metrics/v1' or type(metrics.get('body_char_count')) is not int:
        raise BuildError('invalid content metrics artifact', 'CORRUPT_SNAPSHOT')
    if (preflight.get('schema') != 'naver-smarteditor-preflight/v2'
            or not isinstance(preflight.get('errors'), list)
            or not isinstance(preflight.get('error_codes'), list)
            or not isinstance(preflight.get('review_errors'), list)
            or preflight.get('asset_integrity') != assets
            or preflight.get('content_metrics') != metrics):
        raise BuildError('v2 preflight artifacts disagree', 'CORRUPT_SNAPSHOT')

    image_count = sum(block['type'] == 'image' for block in post['blocks'])
    tag_length = len(' '.join('#' + tag for tag in post['tags']))
    if (preflight.get('episode') != entry['episode'] or post.get('episode') != entry['episode']
            or preflight.get('image_count') != image_count or entry.get('image_count') != image_count
            or preflight.get('tag_string_length') != tag_length or entry.get('tag_string_length') != tag_length
            or preflight.get('content_revision') != entry.get('content_revision')):
        raise BuildError('v2 canonical summary disagrees with episode artifacts', 'CORRUPT_SNAPSHOT')
    if len(assets) == image_count:
        if content_revision(post, assets) != entry.get('content_revision'):
            raise BuildError('v2 canonical revision mismatch', 'CORRUPT_SNAPSHOT')
    elif entry.get('content_revision') is not None:
        raise BuildError('v2 revision exists without complete assets', 'CORRUPT_SNAPSHOT')

    visual = preflight.get('visual_quality')
    if not isinstance(visual, dict):
        raise BuildError('missing v2 visual quality artifact', 'CORRUPT_SNAPSHOT')
    if 'slot_bindings' in visual:
        bindings = validate_slot_bindings(post, visual['slot_bindings'])
        caption_ids = [binding['caption_block_id'] for binding in bindings if binding['caption_block_id']]
        recomputed_metrics = body_metrics(post, excluded_block_ids=caption_ids)
        if metrics != recomputed_metrics:
            raise BuildError('v2 body metrics do not match canonical blocks', 'CORRUPT_SNAPSHOT')
        recomputed_visual, visual_errors = evaluate_v2_visual(post, assets, bindings, requirements)
        if visual != recomputed_visual:
            raise BuildError('v2 visual quality does not match canonical blocks', 'CORRUPT_SNAPSHOT')
        stored_visual_codes = [code for code in preflight['error_codes'] if is_v2_visual_error(code)]
        expected_visual_codes = [code for _, code in visual_errors]
        if stored_visual_codes != expected_visual_codes:
            raise BuildError('v2 visual errors disagree with canonical blocks', 'CORRUPT_SNAPSHOT')

    review_state = preflight.get('content_review')
    review_errors = preflight['review_errors']
    if review_state not in {'ready', 'review_pending', 'stale_review', 'needs_revision', 'invalid_review'}:
        raise BuildError('invalid v2 review summary', 'CORRUPT_SNAPSHOT')
    derived = derive_v2_episode_state(preflight, metrics, requirements, review_state, review_errors)
    compared = ('status', 'errors', 'error_codes', 'body_char_count', 'structure_ready', 'length_ready',
                'editorial_ready', 'visual_ready', 'visual_minimum_met', 'visual_target_met', 'draft_input_ready')
    if any(entry.get(key) != derived[key] for key in compared):
        raise BuildError('v2 readiness summary does not match canonical diagnostics', 'CORRUPT_SNAPSHOT')


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
        requirement_fields = {
            'content_mode', 'primary_style', 'secondary_style', 'min_body_chars',
            'visual_mode', 'min_images_per_episode', 'target_images_per_episode',
            'tag_line_max_chars',
        }
        if (not isinstance(requirements, dict) or set(requirements) != requirement_fields
                or report.get('quality_contract') != 'full-article-v2'):
            raise BuildError('missing v2 quality contract', 'CORRUPT_SNAPSHOT')
        minimum_body = requirements.get('min_body_chars')
        minimum_images = requirements.get('min_images_per_episode')
        target_images = requirements.get('target_images_per_episode')
        tag_limit = requirements.get('tag_line_max_chars')
        visual_mode = requirements.get('visual_mode')
        if (type(minimum_body) is not int or minimum_body < 3000
                or requirements.get('content_mode') != 'full_article'
                or visual_mode not in {'required', 'optional', 'none'}
                or requirements.get('primary_style') not in WRITING_STYLES
                or requirements.get('secondary_style') not in WRITING_STYLES
                or requirements.get('primary_style') == requirements.get('secondary_style')
                or type(tag_limit) is not int or not 0 <= tag_limit <= 100
                or (visual_mode == 'required' and (
                    type(minimum_images) is not int or minimum_images < 3
                    or type(target_images) is not int or target_images < minimum_images
                ))
                or (visual_mode == 'optional' and (minimum_images != 0 or target_images is not None))
                or (visual_mode == 'none' and (minimum_images != 0 or target_images != 0))):
            raise BuildError('invalid v2 requirements', 'CORRUPT_SNAPSHOT')
        for entry in entries:
            validate_v2_snapshot_episode(directory, entry, requirements)
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
