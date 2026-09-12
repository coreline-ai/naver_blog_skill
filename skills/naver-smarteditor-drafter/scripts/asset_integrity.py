"""Decode and fingerprint local static PNG/JPEG assets before upload."""
from __future__ import annotations

import hashlib
import io
import warnings
from pathlib import Path
from typing import Any

from post_contract import BuildError

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
EXTENSIONS = {'.png':'PNG', '.jpg':'JPEG', '.jpeg':'JPEG'}


def inspect_asset(path: Path, allowed_root: Path) -> dict[str, Any]:
    path, root = Path(path), Path(allowed_root).resolve()
    if '..' in path.parts:
        raise BuildError('image path must not contain ..', 'UNSAFE_PATH')
    path = path.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise BuildError('image must be a regular file inside the input root', 'UNSAFE_PATH')
    if path.suffix.lower() not in EXTENSIONS:
        raise BuildError('only static PNG/JPEG images are supported', 'UNSUPPORTED_IMAGE')
    if path.stat().st_size > MAX_FILE_BYTES:
        raise BuildError('image exceeds local 20 MiB safety limit', 'IMAGE_TOO_LARGE')
    with path.open('rb') as stream:
        data = stream.read(MAX_FILE_BYTES+1)
    if len(data)>MAX_FILE_BYTES:
        raise BuildError('image grew beyond local file safety limit', 'IMAGE_TOO_LARGE')
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise BuildError('Pillow is required; image validation was not skipped', 'DEPENDENCY_MISSING') from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                width,height=im.size
                fmt=im.format
                if width<=0 or height<=0 or width*height>MAX_PIXELS:
                    raise BuildError('image exceeds local 40 MP safety limit', 'IMAGE_TOO_LARGE')
                if fmt != EXTENSIONS[path.suffix.lower()] or getattr(im,'n_frames',1)!=1:
                    raise BuildError('image extension/format mismatch or animated image', 'UNSUPPORTED_IMAGE')
                im.verify()
            with Image.open(io.BytesIO(data)) as im:
                im.load()
    except BuildError:
        raise
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise BuildError(f'image cannot be decoded: {path.name}', 'INVALID_IMAGE') from exc
    return {'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),
            'format':fmt,'width':width,'height':height}


def verify_asset(record: dict[str, Any], allowed_root: Path) -> dict[str, Any]:
    current=inspect_asset(Path(record['path']),allowed_root)
    if current!=record:
        raise BuildError('prepared image bytes or identity changed; reprepare and review', 'ASSET_CHANGED')
    return current
