"""Source presentation checks; never rewrite an article or claim factual/UI QA."""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from post_contract import BuildError, validate_link_url

REFERENCE_HEADINGS = {'참고자료', '참고문헌', '출처', '출처및참고자료', '공식확인자료', 'sources', 'references'}
URL_RE = re.compile(r'https?://[^\s<>]+', re.I)


def reference_heading(text: str) -> bool:
    return re.sub(r'\s+', '', text).casefold() in REFERENCE_HEADINGS


def text_items(block: dict):
    kind = block['type']
    if kind in ('paragraph', 'heading'):
        yield block
    elif kind == 'list':
        yield from block['items']
    elif kind == 'callout':
        yield {'text': block['title']}
        yield {'text': block['text']}
    elif kind == 'table':
        for text in [*block['columns'], *(cell for row in block['rows'] for cell in row)]:
            yield {'text': text}


def review_presentation(post: dict, *, source_placement: str = 'end') -> dict:
    if source_placement not in ('end', 'inline'):
        raise BuildError('source placement must be end or inline', 'INVALID_PRESENTATION_POLICY')
    issues, seen, in_refs = [], {}, False
    links = 0
    def issue(code, block, detail):
        issues.append({'code': code, 'block_id': block['id'], 'detail': detail})
    for block in post['blocks']:
        if block['type'] == 'heading':
            is_refs = reference_heading(block['text'])
            if in_refs and not is_refs:
                issue('REFERENCE_SECTION_NOT_TERMINAL', block, 'Move references after public article sections.')
            in_refs = is_refs or in_refs
        for item in text_items(block):
            text = item['text']
            if URL_RE.search(text):
                issue('RAW_URL_DISPLAY', block, 'Use a descriptive linked label, not a full URL in visible text.')
            for mark in item.get('marks', []):
                if mark['type'] != 'link':
                    continue
                url = validate_link_url(mark['url'])
                links += 1
                if source_placement == 'end' and not in_refs:
                    issue('INLINE_SOURCE_LINK', block, 'Default profile places sources at the end; explicit inline requests use the inline policy.')
                p = urlsplit(url)
                key = urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, p.query, p.fragment))
                if key in seen:
                    issue('DUPLICATE_SOURCE_LINK', block, f'The same URL already occurs in {seen[key]}; consolidate without deleting facts.')
                else:
                    seen[key] = block['id']
    return {'schema': 'naver-presentation-review/v1', 'status': 'failed' if issues else 'passed',
            'source_placement': source_placement, 'link_count': links, 'unique_link_count': len(seen),
            'issues': issues, 'factual_review': 'not_evaluated', 'ui_review': 'not_performed'}
