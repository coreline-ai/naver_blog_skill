#!/usr/bin/env python3
"""Build deterministic naver-post/v1 packages from Markdown or structured JSON."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from post_contract import (BuildError, check_editorial, require_int, require_text, safe_segment, validate_post, load_json_object)
from asset_integrity import inspect_asset


SCHEMA = "naver-post/v1"
RUN_SCHEMA = "naver-smarteditor-run/v2"
RENDER_POLICY = "smarteditor-subset/v1"
IMAGE_RE = re.compile(r"^!\[([^]]*)\]\((?:<([^>]+)>|([^\s)]+))\)\s*$")
HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
LIST_RE = re.compile(r"^\s*(?:(\d+)\.|[-+*])\s+(.+?)\s*$")
LABEL_RE = re.compile(r"^\*\*([^*]+)\*\*\s*$")
EPISODE_RE = re.compile(r"episode-(\d+)", re.IGNORECASE)
TABLE_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")
INLINE_RE = re.compile(r"(\*\*([^*]+)\*\*|`([^`]+)`)")

CALLOUT_LABELS = {
    "핵심 요약": ("summary", "quotation_line"),
    "다음 편 예고": ("next", "quotation_line"),
    "시리즈 활용 방법": ("series_use", "quotation_line"),
    "함께 생각해볼 질문": ("question", "quotation_line"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _episode_number(path: Path, data: dict[str, Any] | None = None) -> int | None:
    identities = []
    if data is not None and data.get('episode') is not None:
        identities.append(require_int(data['episode'], 'episode', minimum=1))
    for value in (path.stem, path.parent.name):
        match = EPISODE_RE.fullmatch(value)
        if match:
            identities.append(require_int(int(match.group(1)), 'episode', minimum=1))
    if len(set(identities)) > 1:
        raise BuildError('filename, parent folder and internal episode disagree', 'EPISODE_IDENTITY_CONFLICT')
    return identities[0] if identities else None


def _inline(raw: str) -> dict[str, Any]:
    """Preserve code-point offsets while explicitly flattening links/emphasis."""
    require_text(raw, 'inline text', empty=True)
    pattern = re.compile(r'(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]\n]+)\]\(([^)\s]+)\)|(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!\w)_([^_\n]+)_(?!\w))')
    parts, marks, cursor, length = [], [], 0, 0
    for match in pattern.finditer(raw):
        prefix = raw[cursor:match.start()]
        parts.append(prefix); length += len(prefix)
        bold, code, label, url, emphasis, underscore = match.groups()[1:]
        if url is not None:
            if urlsplit(url).scheme not in ('http','https') or not urlsplit(url).netloc or '(' in url:
                raise BuildError('unsupported link URL or nested link syntax', 'UNSUPPORTED_MARKDOWN')
            value = f'{label} ({url})'
        else:
            value = next(v for v in (bold,code,emphasis,underscore) if v is not None)
        if bold is not None or code is not None:
            marks.append({'start':length,'end':length+len(value),'type':'bold' if bold is not None else 'code'})
        parts.append(value); length+=len(value); cursor=match.end()
    parts.append(raw[cursor:])
    combined=''.join(parts)
    leading=len(combined)-len(combined.lstrip())
    result={'text':combined.strip()}
    if marks:
        result['marks']=[{**m,'start':m['start']-leading,'end':m['end']-leading} for m in marks]
    return result


def _parse_table_row(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    cells = re.split(r"(?<!\\)\|", value)
    return [cell.replace(r"\|", "|").strip() for cell in cells]


def _is_table_separator(line: str) -> bool:
    cells = _parse_table_row(line)
    return bool(cells) and all(TABLE_SEPARATOR_RE.fullmatch(cell) for cell in cells)


def _is_block_start(lines: list[str], index: int) -> bool:
    line = lines[index]
    if not line.strip():
        return True
    if HEADING_RE.match(line) or IMAGE_RE.match(line) or LABEL_RE.match(line):
        return True
    if line.strip() == "---" or LIST_RE.match(line):
        return True
    return index + 1 < len(lines) and "|" in line and _is_table_separator(lines[index + 1])


def _resolve_image(raw_path: str, source: Path, project_root: Path) -> Path:
    candidate = Path(raw_path).expanduser()
    if ".." in candidate.parts:
        raise BuildError(f"image path must not contain '..': {raw_path}", 'UNSAFE_PATH')
    if not candidate.is_absolute():
        candidate = source.parent / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise BuildError(f"image path escapes project root: {raw_path}", 'UNSAFE_PATH') from exc
    if not resolved.is_file():
        raise BuildError(f"image file does not exist: {resolved}", 'ASSET_MISSING')
    return resolved


def _normalize_tags(values: Any) -> list[str]:
    if not isinstance(values, list):
        raise BuildError('tags must be an array')
    tags = []
    for raw in values:
        require_text(raw, 'tag')
        tag = raw.strip().removeprefix('#').strip()
        if not tag or '#' in tag or any(c.isspace() for c in tag):
            raise BuildError('tag must not be empty or contain #/whitespace')
        if tag in tags:
            raise BuildError(f'duplicate tag: {tag}')
        tags.append(tag)
    if len(' '.join('#'+tag for tag in tags)) > 100:
        raise BuildError('tag string exceeds 100 characters')
    return tags


def _assign_ids(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, block in enumerate(blocks, 1):
        normalized = dict(block)
        normalized.setdefault("id", f"b{index:03d}")
        result.append(normalized)
    return result


def parse_markdown(source: Path, project_root: Path, *, text: str | None = None) -> tuple[dict[str, Any], list[str]]:
    text = source.read_text(encoding="utf-8") if text is None else require_text(text, 'Markdown text')
    check_editorial(text)
    lines = text.splitlines()
    for number, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if (re.match(r'#{4,}\s|`{3,}|~{3,}', stripped)
                or re.match(r'^(?: {4}|\t)\S', line)
                or (not IMAGE_RE.fullmatch(line) and re.search(r'</?[A-Za-z][^>]*>|<!--', line))
                or re.search(r'\[[^]]+\]\[[^]]*\]|^\s*\[[^]]+\]:', line)
                or ('![' in line and not IMAGE_RE.fullmatch(line))
                or (LIST_RE.match(line) and line != line.lstrip())
                or re.match(r'^\s*[-*+]\s+\[[ xX]\]', line)):
            raise BuildError(f'unsupported Markdown syntax on line {number}', 'UNSUPPORTED_MARKDOWN')
    h1_lines = [m.group(2).strip() for line in lines if (m := HEADING_RE.match(line)) and len(m.group(1)) == 1]
    if len(h1_lines) != 1:
        raise BuildError(f"Markdown must contain exactly one H1 title; found {len(h1_lines)}")

    title = _inline(h1_lines[0])["text"]
    if not title:
        raise BuildError("title must not be empty")

    blocks: list[dict[str, Any]] = []
    tags: list[str] = []
    warnings: list[str] = []
    image_paths: set[Path] = set()
    in_tags = False
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue

        if in_tags:
            if stripped == '---':
                index += 1
                continue
            if not re.fullmatch(r'#[^\s#]+(?:\s+#[^\s#]+)*', stripped):
                raise BuildError(f'non-tag content found after tag label on line {index + 1}')
            tags.extend(value[1:] for value in stripped.split())
            index += 1
            continue

        heading_match = HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            if level == 1:
                index += 1
                continue
            inline = _inline(heading_match.group(2))
            blocks.append(
                {
                    "type": "heading",
                    "level": level,
                    "style": "quotation_bubble" if level == 2 else "subtitle",
                    **inline,
                }
            )
            index += 1
            continue

        label_match = LABEL_RE.match(line)
        if label_match:
            label = label_match.group(1).strip()
            if label == "태그":
                in_tags = True
            else:
                variant, style = CALLOUT_LABELS.get(label, ("label", "quotation_line"))
                blocks.append(
                    {
                        "type": "callout",
                        "variant": variant,
                        "style": style,
                        "title": label,
                        "text": "",
                    }
                )
            index += 1
            continue

        image_match = IMAGE_RE.match(line)
        if image_match:
            raw_path = image_match.group(2) or image_match.group(3) or ""
            resolved = _resolve_image(raw_path, source, project_root)
            if resolved in image_paths:
                raise BuildError(f"duplicate image path: {resolved}")
            image_paths.add(resolved)
            blocks.append(
                {
                    "type": "image",
                    "path": str(resolved),
                    "alt": image_match.group(1).strip(),
                }
            )
            index += 1
            continue

        if stripped == "---":
            blocks.append({"type": "divider"})
            index += 1
            continue

        if index + 1 < len(lines) and "|" in line and _is_table_separator(lines[index + 1]):
            columns = [_inline(c)["text"] for c in _parse_table_row(line)]
            rows: list[list[str]] = []
            index += 2
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                row = [_inline(c)["text"] for c in _parse_table_row(lines[index])]
                if len(row) != len(columns):
                    raise BuildError(f"table row has {len(row)} cells; expected {len(columns)} on line {index + 1}")
                rows.append(row)
                index += 1
            blocks.append({"type": "table", "columns": columns, "rows": rows})
            continue

        list_match = LIST_RE.match(line)
        if list_match:
            ordered = list_match.group(1) is not None
            items: list[dict[str, Any]] = []
            while index < len(lines):
                item_match = LIST_RE.match(lines[index])
                if not item_match or (item_match.group(1) is not None) != ordered:
                    break
                items.append(_inline(item_match.group(2)))
                index += 1
            blocks.append(
                {
                    "type": "list",
                    "style": "ordered" if ordered else "unordered",
                    "items": items,
                }
            )
            continue

        paragraph_lines = [stripped]
        index += 1
        while index < len(lines) and not _is_block_start(lines, index):
            paragraph_lines.append(lines[index].strip())
            index += 1
        raw_paragraph = " ".join(value for value in paragraph_lines if value)
        if raw_paragraph.startswith(">"):
            warnings.append("blockquote downgraded to paragraph")
            raw_paragraph = raw_paragraph.lstrip("> ")
        blocks.append({"type": "paragraph", **_inline(raw_paragraph)})

    return (
        {
            "schema": SCHEMA,
            "episode": _episode_number(source),
            "source": str(source.resolve()),
            "title": title,
            "blocks": _assign_ids(blocks),
            "tags": _normalize_tags(tags),
        },
        warnings,
    )


def _structured_item_text(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        return _inline(item)
    if not isinstance(item, dict):
        raise BuildError('list items must be strings or objects')
    if set(item) - {'title','label','text','marks','checked'}:
        raise BuildError('unsupported list item fields')
    title = require_text(item.get('title',item.get('label','')), 'item title', empty=True).strip()
    text = require_text(item.get('text',''), 'item text', empty=True)
    if 'marks' in item:
        if title:
            raise BuildError('marks require final text, not a title/text combination')
        return copy.deepcopy(item)
    result = _inline(f'{title}: {text}' if title and text else title or text)
    if title and text and not result.get('marks'):
        result['marks']=[{'start':0,'end':len(title),'type':'bold'}]
    if 'checked' in item:
        result['checked']=item['checked']
    return result


def _normalize_structured_block(raw: Any, source: Path, project_root: Path) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get('type'), str):
        raise BuildError('every content block needs a string type')
    kind=raw['type']
    def inline():
        if 'marks' in raw:
            return {'text':require_text(raw.get('text'),'text'),'marks':copy.deepcopy(raw['marks'])}
        return _inline(require_text(raw.get('text'),'text'))
    if kind == 'paragraph':
        block={'type':kind,**inline()}
    elif kind == 'heading':
        level=raw.get('level',2)
        if type(level) is not int or level not in (2,3):
            raise BuildError('heading level must be 2 or 3')
        block={'type':kind,'level':level,'style':raw.get('style','quotation_bubble' if level==2 else 'subtitle'),**inline()}
    elif kind == 'image':
        block={'type':kind,'path':str(_resolve_image(require_text(raw.get('path'),'image path'),source,project_root)),
               'alt':require_text(raw.get('alt',''),'alt',empty=True)}
        if 'caption' in raw: block['caption']=require_text(raw['caption'],'caption',empty=True)
    elif kind in ('list','steps','checklist'):
        if not isinstance(raw.get('items'),list) or not raw['items']:
            raise BuildError('list requires non-empty items array')
        style=raw.get('style',{'list':'unordered','steps':'ordered','checklist':'checklist'}[kind])
        block={'type':'list','style':style,'items':[_structured_item_text(i) for i in raw['items']]}
    elif kind == 'comparison':
        if not isinstance(raw.get('items'),list) or not raw['items']:
            raise BuildError('comparison requires non-empty items array')
        rows=[]
        for item in raw['items']:
            if not isinstance(item,dict) or set(item)-{'label','text'}:
                raise BuildError('comparison items require label/text objects')
            rows.append([require_text(item.get('label'),'label'),require_text(item.get('text'),'text')])
        block={'type':'table','columns':['항목','설명'],'rows':rows}
    elif kind == 'table':
        block={'type':kind,'columns':copy.deepcopy(raw.get('columns')),'rows':copy.deepcopy(raw.get('rows'))}
    elif kind == 'callout':
        variant=raw.get('variant','note')
        block={'type':kind,'variant':variant,'style':raw.get('style','quotation_line' if variant=='summary' else 'quotation_postit'),
               'title':require_text(raw.get('title',''),'callout title',empty=True),'text':require_text(raw.get('text',''),'callout text',empty=True)}
    elif kind == 'divider':
        block={'type':kind}
    else:
        raise BuildError(f'unsupported structured block type: {kind}')
    allowed=set(block)|{'id'}
    if kind in ('steps','checklist'): allowed|={'items','style'}
    if kind=='comparison': allowed={'type','id','items'}
    if set(raw)-allowed:
        raise BuildError(f'unsupported fields on {kind}: {sorted(set(raw)-allowed)}')
    if 'id' in raw: block['id']=raw['id']
    return block


def _load_json_text(source: Path) -> dict[str, Any]:
    return load_json_object(source, allow_fence=True)


def parse_structured(source: Path, project_root: Path) -> tuple[dict[str, Any], list[str]]:
    data = _load_json_text(source)
    if data.get('schema') not in (None, SCHEMA):
        raise BuildError('unsupported schema')
    episode = _episode_number(source,data)
    if data.get('schema') == SCHEMA:
        validate_post(data)
        if episode != data['episode']:
            raise BuildError('canonical episode conflicts with filename/folder', 'EPISODE_IDENTITY_CONFLICT')
        for block in data['blocks']:
            if block['type']=='image' and str(_resolve_image(block['path'], source, project_root)) != block['path']:
                raise BuildError('canonical image path must already be resolved', 'UNSAFE_PATH')
        return copy.deepcopy(data), []
    title = require_text(data.get('title'),'title').strip()
    if 'blocks' in data and 'content' in data:
        raise BuildError('provide blocks or content, not both')
    raw_blocks = data.get('blocks',data.get('content'))
    if not isinstance(raw_blocks,list):
        raise BuildError('structured input requires a blocks or content array')
    blocks=[_normalize_structured_block(raw,source,project_root) for raw in raw_blocks]
    tags=_normalize_tags(data.get('tags',data.get('seo_tags',[])))
    if 'tags' in data and 'seo_tags' in data:
        raise BuildError('provide tags or seo_tags, not both')
    warnings=[]
    if data.get('image_prompts') and not any(b['type']=='image' for b in blocks):
        warnings.append('image_prompts are not uploadable image blocks')
    return {'schema':SCHEMA,'episode':episode,'source':str(source.resolve()),'title':title,
            'blocks':_assign_ids(blocks),'tags':tags}, warnings


def build_post(source: Path, project_root: Path, *, markdown_text: str | None = None) -> tuple[dict[str, Any], list[str]]:
    source=Path(source).expanduser().resolve(); project_root=Path(project_root).expanduser().resolve()
    if not source.is_file():
        raise BuildError(f'input file does not exist: {source}')
    if not source.is_relative_to(project_root):
        raise BuildError(f'input file escapes project root: {source}', 'UNSAFE_PATH')
    try:
        if markdown_text is not None and source.suffix.lower()!='.md':
            raise BuildError('in-memory composition requires a Markdown source')
        if source.suffix.lower()=='.md': post,warnings=parse_markdown(source,project_root,text=markdown_text)
        elif source.suffix.lower() in ('.json','.txt'): post,warnings=parse_structured(source,project_root)
        else: raise BuildError(f'unsupported input extension: {source.suffix}')
        validate_post(post)
        paths=[b['path'] for b in post['blocks'] if b['type']=='image']
        if len(set(paths))!=len(paths): raise BuildError('duplicate image path')
        raw=source.read_text(encoding='utf-8') if markdown_text is None else markdown_text
        if source.suffix.lower()=='.md' or 'schema' not in _load_json_text(source):
            if re.search(r'\[[^]\n]+\]\(https?://',raw): warnings.append('links rendered as label (URL)')
            if re.search(r'(?<!\*)\*[^*\n]+\*(?!\*)|(?<!\w)_[^_\n]+_(?!\w)',raw):
                warnings.append('italic emphasis rendered as plain text')
        for b in post['blocks']:
            if b['type'] in ('list','table') or b.get('level')==3:
                msg=f"{b['type']} uses documented text-render fallback"
                if msg not in warnings: warnings.append(msg)
        return post,warnings
    except BuildError:
        raise
    except (ValueError,TypeError,KeyError) as exc:
        raise BuildError(f'invalid input value: {exc}') from exc


def content_revision(post: dict[str, Any], assets: list[dict[str, Any]]) -> str:
    semantic=copy.deepcopy(post)
    semantic.pop('source',None)
    by_path={a['path']:a for a in assets}
    for block in semantic['blocks']:
        if block['type']=='image':
            asset=by_path[block.pop('path')]
            block['asset']={k:v for k,v in asset.items() if k!='path'}
    data={'render_policy':RENDER_POLICY,'post':semantic}
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def preflight_report(
    post: dict[str, Any], source: Path, warnings: list[str], *,
    expected_images: int | None = None, expected_tags: int | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    validate_post(post)
    for value,field in ((expected_images,'expected_images'),(expected_tags,'expected_tags')):
        if value is not None: require_int(value,field)
    counts={}
    for b in post['blocks']: counts[b['type']]=counts.get(b['type'],0)+1
    errors=[];error_codes=[];assets=[]
    def error(message,code): errors.append(message);error_codes.append(code)
    if expected_images is not None and counts.get('image',0)!=expected_images:
        error(f"expected {expected_images} images; found {counts.get('image',0)}",'IMAGE_COUNT_MISMATCH')
    if expected_tags is not None and len(post['tags'])!=expected_tags:
        error(f"expected {expected_tags} tags; found {len(post['tags'])}",'TAG_COUNT_MISMATCH')
    meaningful=any((b['type']=='paragraph' and b['text'].strip()) or
                   (b['type']=='list' and b['items']) or (b['type']=='table' and b['rows']) or
                   (b['type']=='callout' and b['text'].strip()) for b in post['blocks'])
    if not meaningful: error('informative post requires substantive body content','BODY_REQUIRED')
    root=Path(project_root or source.parent).resolve()
    for b in post['blocks']:
        if b['type']=='image':
            try: assets.append(inspect_asset(Path(b['path']),root))
            except (BuildError,OSError) as exc: error(str(exc),getattr(exc,'code','ASSET_READ_ERROR'))
    revision=content_revision(post,assets) if len(assets)==counts.get('image',0) else None
    return {'schema':'naver-smarteditor-preflight/v2','status':'passed' if not errors else 'failed',
            'episode':post.get('episode'),'title':post['title'],'source':str(source.resolve()),
            'source_sha256':_sha256(source),'content_revision':revision,'render_policy':RENDER_POLICY,
            'block_count':len(post['blocks']),'block_counts':counts,'image_count':counts.get('image',0),
            'tag_count':len(post['tags']),'tag_string_length':len(' '.join('#'+t for t in post['tags'])),
            'asset_integrity':assets,'warnings':list(warnings),'errors':errors,'error_codes':error_codes,
            'content_review':'not_evaluated','ui_verification':'not_performed'}


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _write_json(path: Path, data: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n")


def _discover_inputs(root: Path, episode_min: int | None, episode_max: int | None) -> list[Path]:
    candidates: list[tuple[int, Path]] = []
    seen: set[int] = set()
    for path in root.rglob("episode-*.*"):
        if path.suffix.lower() not in {".md", ".json", ".txt"}:
            continue
        episode = _episode_number(path)
        if episode is None:
            continue
        if episode_min is not None and episode < episode_min:
            continue
        if episode_max is not None and episode > episode_max:
            continue
        if episode in seen:
            raise BuildError(f"multiple input files found for episode {episode:02d}")
        seen.add(episode)
        candidates.append((episode, path.resolve()))
    return [path for _, path in sorted(candidates, key=lambda item: item[0])]


def _destination_name(post: dict[str, Any], source: Path) -> str:
    episode=post.get('episode')
    if episode is not None: return f'episode-{episode:02d}'
    try: return safe_segment(source.stem,'source name')
    except BuildError: return 'standalone-'+hashlib.sha256(source.stem.encode()).hexdigest()[:16]


def _prepare_one(source: Path, project_root: Path, *, expected_images: int | None,
                 expected_tags: int | None) -> tuple[dict[str, Any], dict[str, Any]]:
    post,warnings=build_post(source,project_root)
    report=preflight_report(post,source,warnings,expected_images=expected_images,
                            expected_tags=expected_tags,project_root=project_root)
    if report['errors']:
        raise BuildError('; '.join(report['errors']),report['error_codes'][0])
    return post,report


def safe_run_directory(output_root: Path, run_id: str) -> Path:
    safe_segment(run_id, 'run id')
    raw=Path(output_root).expanduser()
    if raw.is_symlink() or '..' in raw.parts:
        raise BuildError('output root must not contain ..','UNSAFE_PATH')
    root=raw.resolve()
    candidate=root/run_id
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(root):
        raise BuildError('run directory escapes output root or is a symlink','UNSAFE_PATH')
    if candidate.exists() and not candidate.is_dir():
        raise BuildError('run directory is not a directory','UNSAFE_PATH')
    return candidate


def _json_string(data: Any) -> str:
    return json.dumps(data,ensure_ascii=False,indent=2,sort_keys=False)+'\n'


def write_prepared_run(run_directory: Path, artifacts: dict[str,str], *, reuse: bool=False) -> None:
    """Commit a new immutable snapshot; an exact pure-prepare rerun may be reused."""
    run_directory.parent.mkdir(parents=True,exist_ok=True)
    lock=run_directory.parent/('.prepare-'+run_directory.name+'.lock')
    try: fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError as exc:
        raise BuildError('preparation writer is locked; inspect incomplete run before retry','PREPARE_LOCKED') from exc
    os.close(fd)
    staging=None
    try:
        if run_directory.is_symlink(): raise BuildError('run directory is a symlink','UNSAFE_PATH')
        if run_directory.exists():
            if not reuse:
                raise BuildError('output run already exists; use a new --run-id (not --force for resume)','RUN_EXISTS')
            existing=[p for p in run_directory.rglob('*') if p.is_file() or p.is_symlink()]
            if (any(p.is_symlink() for p in run_directory.rglob('*')) or
                    set(str(p.relative_to(run_directory)) for p in existing)!=set(artifacts) or
                    any((run_directory/k).read_text(encoding='utf-8')!=v for k,v in artifacts.items())):
                raise BuildError('--force cannot overwrite changed preparation or saved execution history; use a new --run-id','IMMUTABLE_RUN')
            return
        staging=Path(tempfile.mkdtemp(prefix='.'+run_directory.name+'.staging-',dir=run_directory.parent))
        # complete.json is the final marker. Staging never appears as a committed run.
        for name in sorted(artifacts,key=lambda name:name=='complete.json'):
            _atomic_write(staging/name,artifacts[name])
        if run_directory.exists(): raise BuildError('output appeared during preparation','RUN_EXISTS')
        os.rename(staging,run_directory)
        staging=None
    finally:
        lock.unlink(missing_ok=True)
        # Keep an interrupted staging directory as evidence; never delete existing runs.


def run(args: argparse.Namespace) -> dict[str, Any]:
    project_root=Path(args.project_root or Path.cwd()).expanduser().resolve()
    run_directory=safe_run_directory(Path(args.output_root),args.run_id)
    for value,field in ((args.episode_min,'episode_min'),(args.episode_max,'episode_max')):
        if value is not None: require_int(value,field,minimum=1)
    if args.episode_min is not None and args.episode_max is not None and args.episode_min>args.episode_max:
        raise BuildError('episode_min must not exceed episode_max')
    if args.batch:
        if not args.input_root: raise BuildError('--batch requires --input-root')
        input_root=Path(args.input_root).expanduser().resolve()
        if not input_root.is_dir() or not input_root.is_relative_to(project_root):
            raise BuildError('input root must be a directory inside project root','UNSAFE_PATH')
        sources=_discover_inputs(input_root,args.episode_min,args.episode_max)
    else:
        if not args.input: raise BuildError('single mode requires --input')
        sources=[Path(args.input).expanduser().resolve()]
    requested=(list(range(args.episode_min,args.episode_max+1)) if args.batch and
               args.episode_min is not None and args.episode_max is not None else None)
    if not sources and requested is None: raise BuildError('no episode input files found')
    prepared=[];episodes=[];destinations=set();failures=0
    for source in sources:
        episode=None
        try:
            episode=_episode_number(source)
            post,report=_prepare_one(source,project_root,expected_images=args.expected_images,expected_tags=args.expected_tags)
            destination=_destination_name(post,source)
            if destination in destinations: raise BuildError('duplicate output destination','EPISODE_IDENTITY_CONFLICT')
            destinations.add(destination)
            prepared.append((source,post,report))
            episodes.append({'episode':post['episode'],'title':post['title'],'source':str(source),'status':'prepared','error':None})
        except (BuildError,OSError,UnicodeError) as exc:
            failures+=1
            episodes.append({'episode':episode,'title':None,'source':str(source),'status':'failed','error':str(exc),'error_code':getattr(exc,'code','INPUT_READ_ERROR')})
    found={_episode_number(source) for source in sources}
    missing=sorted(set(requested or [])-found)
    for ep in missing:
        failures+=1
        episodes.append({'episode':ep,'title':None,'source':None,'status':'missing','error':'requested episode is missing','error_code':'MISSING_EPISODE'})
    prepared_queue=[post['episode'] if post['episode'] is not None else source.stem for source,post,_ in prepared]
    report={'schema':RUN_SCHEMA,'status':'prepared' if failures==0 else 'preflight_failed',
            'run_id':args.run_id,'project_root':str(project_root),'requested_episodes':requested,
            'missing':missing,'queue':prepared_queue if failures==0 else [],'prepared_queue':prepared_queue,
            'ui_executable':False,'content_review':'not_evaluated',
            'totals':{'inputs':len(sources),'prepared':len(prepared),'failed':failures,
                      'blocks':sum(len(p['blocks']) for _,p,_ in prepared),
                      'images':sum(r['image_count'] for _,_,r in prepared),'tags':sum(r['tag_count'] for _,_,r in prepared)},
            'episodes':episodes}
    if not args.check:
        artifacts={}
        for source,post,preflight in prepared:
            name=_destination_name(post,source)
            artifacts[name+'/naver-post.json']=_json_string(post)
            artifacts[name+'/preflight-report.json']=_json_string(preflight)
            artifacts[name+'/asset-integrity.json']=_json_string({'schema':'naver-assets/v1','assets':preflight['asset_integrity']})
        artifacts['run-report.json']=_json_string(report)
        if not failures:
            artifacts['complete.json']=_json_string({'schema':'naver-prepared-snapshot/v1',
                'files':{key:hashlib.sha256(value.encode()).hexdigest() for key,value in sorted(artifacts.items())}})
        write_prepared_run(run_directory,artifacts,reuse=args.force)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="single Markdown, JSON, or fenced JSON text file")
    parser.add_argument("--input-root", help="root containing episode-XX input files")
    parser.add_argument("--output-root", required=True, help="directory that will contain the run")
    parser.add_argument("--run-id", default="run", help="non-empty output run directory name")
    parser.add_argument("--project-root", help="allowed root for inputs and local images; defaults to cwd")
    parser.add_argument("--batch", action="store_true", help="discover and prepare episode files")
    parser.add_argument("--check", action="store_true", help="validate and print the report without writing")
    parser.add_argument("--force", action="store_true", help="reuse only an exactly matching pure prepared run; never overwrites or resumes saved drafts")
    parser.add_argument("--episode-min", type=int)
    parser.add_argument("--episode-max", type=int)
    parser.add_argument("--expected-images", type=int)
    parser.add_argument("--expected-tags", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", args.run_id):
        parser.error("--run-id must be one safe path segment")
    if bool(args.input) == bool(args.input_root):
        parser.error("provide exactly one of --input or --input-root")
    try:
        report = run(args)
    except (BuildError, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["totals"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
