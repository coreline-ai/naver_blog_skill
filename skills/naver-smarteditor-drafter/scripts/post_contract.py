"""Strict, lossless naver-post/v1 validation shared by input adapters."""
from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any

SCHEMA = 'naver-post/v1'
EDITORIAL_RE = re.compile(r'게시\s*본문\s*제외|편집자용\s*(?:시리즈\s*안내|메모|발행\s*패키지)|\[시리즈\s*식별\s*코드\s*:')


class BuildError(ValueError):
    def __init__(self, message: str, code: str = 'INVALID_INPUT'):
        super().__init__(message)
        self.code = code


def load_json_object(path: Path, *, allow_fence: bool = False) -> dict[str, Any]:
    """Load strict JSON data, never execute instructions embedded in it."""
    raw = Path(path).read_text(encoding='utf-8').strip()
    if allow_fence:
        fence = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', raw, re.DOTALL | re.IGNORECASE)
        if fence:
            raw = fence.group(1)
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise BuildError(f'duplicate JSON key: {key}')
            value[key] = item
        return value
    def invalid_constant(value):
        raise BuildError(f'non-finite JSON value: {value}')
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    except json.JSONDecodeError as exc:
        raise BuildError(f'invalid JSON: {exc.msg}') from exc
    if not isinstance(value, dict):
        raise BuildError('JSON root must be an object')
    return value


def require_text(value: Any, field: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or '\x00' in value or (not empty and not value.strip()):
        raise BuildError(f'{field} must be a {"possibly empty" if empty else "non-empty"} string')
    return value


def require_int(value: Any, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise BuildError(f'{field} must be an integer >= {minimum}')
    return value


def check_editorial(text: str) -> None:
    if EDITORIAL_RE.search(text):
        raise BuildError('body contains editorial metadata; supply an unambiguous body-only file',
                         'EDITORIAL_BOUNDARY_AMBIGUOUS')


def safe_segment(value: Any, field: str = 'path segment') -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
        raise BuildError(f'{field} must be one safe path segment', 'UNSAFE_PATH')
    return value


def validate_marks(item: dict[str, Any]) -> None:
    text = require_text(item.get('text'), 'text')
    if 'marks' not in item:
        return
    marks = item['marks']
    if not isinstance(marks, list):
        raise BuildError('marks must be an array')
    seen: list[dict[str, Any]] = []
    for mark in marks:
        if not isinstance(mark, dict) or set(mark) != {'start', 'end', 'type'}:
            raise BuildError('mark requires only start, end, type')
        start = require_int(mark['start'], 'mark.start')
        end = require_int(mark['end'], 'mark.end', minimum=1)
        if mark['type'] not in ('bold', 'code') or not start < end <= len(text):
            raise BuildError('invalid mark type or code-point bounds')
        if any(m['type'] == mark['type'] and max(start, m['start']) < min(end, m['end']) for m in seen):
            raise BuildError('duplicate or overlapping marks of the same type')
        seen.append(mark)


def _keys(value: dict, allowed: set[str], required: set[str], label: str) -> None:
    if set(value) - allowed or required - set(value):
        raise BuildError(f'{label}: unsupported or missing fields: {sorted(set(value)-allowed)} / {sorted(required-set(value))}')


def validate_post(post: Any) -> None:
    if not isinstance(post, dict):
        raise BuildError('post must be an object')
    fields = {'schema','episode','source','title','blocks','tags'}
    _keys(post, fields, fields, 'post')
    if post['schema'] != SCHEMA:
        raise BuildError('unsupported canonical schema')
    if post['episode'] is not None:
        require_int(post['episode'], 'episode', minimum=1)
    source = require_text(post['source'], 'source')
    if not Path(source).is_absolute():
        raise BuildError('canonical source must be absolute provenance')
    title = require_text(post['title'], 'title')
    if '\n' in title or '\r' in title:
        raise BuildError('title must be a single line')
    check_editorial(title)
    if not isinstance(post['tags'], list):
        raise BuildError('tags must be an array')
    for tag in post['tags']:
        require_text(tag, 'tag')
        if any(c.isspace() for c in tag) or '#' in tag:
            raise BuildError('canonical tags must exclude # and whitespace')
    if len(set(post['tags'])) != len(post['tags']):
        raise BuildError('duplicate tag')
    if len(' '.join('#'+t for t in post['tags'])) > 100:
        raise BuildError('tag string exceeds 100 characters')
    if not isinstance(post['blocks'], list):
        raise BuildError('blocks must be an array')
    seen = set()
    styles = {'heading': {'quotation_bubble','subtitle'}, 'list': {'unordered','ordered','checklist'},
              'callout': {'quotation_line','quotation_bubble','quotation_postit'}}
    extra = {'paragraph': {'text','marks'}, 'heading': {'text','marks','level','style'},
             'image': {'path','alt','caption'}, 'list': {'style','items'},
             'table': {'columns','rows'}, 'callout': {'variant','title','text','style'}, 'divider': set()}
    for block in post['blocks']:
        if not isinstance(block, dict) or not isinstance(block.get('type'), str) or block['type'] not in extra:
            raise BuildError('unsupported canonical block type')
        kind = block['type']
        required = {'id','type'} | (extra[kind]-{'marks','caption'})
        _keys(block, {'id','type'}|extra[kind], required, kind)
        bid = safe_segment(block['id'], 'block id')
        if bid in seen:
            raise BuildError(f'duplicate block id: {bid}')
        seen.add(bid)
        if kind in styles and (not isinstance(block['style'], str) or block['style'] not in styles[kind]):
            raise BuildError(f'unsupported {kind} style')
        if kind in ('paragraph','heading'):
            validate_marks(block); check_editorial(block['text'])
        if kind == 'heading':
            if type(block['level']) is not int or block['level'] not in (2,3):
                raise BuildError('heading level must be 2 or 3')
            if block['style'] != {2: 'quotation_bubble', 3: 'subtitle'}[block['level']]:
                raise BuildError('heading level/style combination is unsupported')
        elif kind == 'image':
            if not Path(require_text(block['path'], 'image.path')).is_absolute():
                raise BuildError('canonical image path must be absolute')
            require_text(block['alt'], 'image.alt', empty=True)
            if 'caption' in block:
                check_editorial(require_text(block['caption'], 'image.caption', empty=True))
        elif kind == 'list':
            if not isinstance(block['items'], list) or not block['items']:
                raise BuildError('list requires non-empty items')
            for item in block['items']:
                if not isinstance(item, dict):
                    raise BuildError('canonical list items must be objects')
                _keys(item, {'text','marks','checked'}, {'text'}, 'list item')
                if 'checked' in item and (type(item['checked']) is not bool or block['style'] != 'checklist'):
                    raise BuildError('checked is only a boolean on checklist items')
                validate_marks(item); check_editorial(item['text'])
        elif kind == 'table':
            if not isinstance(block['columns'], list) or not block['columns'] or not isinstance(block['rows'], list):
                raise BuildError('table requires columns and rows arrays')
            for c in block['columns']:
                check_editorial(require_text(c,'column'))
            for row in block['rows']:
                if not isinstance(row,list) or len(row)!=len(block['columns']):
                    raise BuildError('table row width must match columns')
                for cell in row:
                    check_editorial(require_text(cell,'cell',empty=True))
        elif kind == 'callout':
            if block['variant'] not in ('summary','next','series_use','question','label','note','warning'):
                raise BuildError('unsupported callout variant')
            for field in ('title','text'):
                check_editorial(require_text(block[field],f'callout.{field}',empty=True))
            if not (block['title'].strip() or block['text'].strip()):
                raise BuildError('empty callout')
