"""Tub discovery and image loading using donkeycar Tub (read-only)."""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from donkeycar.parts.tub_v2 import Tub


@dataclass
class TubSession:
    path: str
    tub: Tub
    records: List[Dict[str, Any]] = field(default_factory=list)
    image_key: str = 'cam/image_array'
    inputs: List[str] = field(default_factory=list)
    types: List[str] = field(default_factory=list)


_sessions: Dict[str, TubSession] = {}


def _normalize_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def open_tub(path: str) -> TubSession:
    """Open a tub directory and cache its non-deleted records."""
    path = _normalize_path(path)
    if not os.path.isdir(path):
        raise FileNotFoundError(f'Tub path is not a directory: {path}')
    manifest = os.path.join(path, 'manifest.json')
    if not os.path.isfile(manifest):
        raise FileNotFoundError(
            f'No manifest.json found in {path} — is this a DonkeyCar tub?'
        )

    if path in _sessions:
        try:
            _sessions[path].tub.close()
        except Exception:
            pass

    tub = Tub(path, read_only=True)
    records = list(tub)
    # Tub constructor keeps empty inputs; manifest holds the on-disk schema.
    inputs = list(tub.manifest.inputs or tub.inputs or [])
    types = list(tub.manifest.types or tub.types or [])
    image_key = 'cam/image_array'
    for key, typ in zip(inputs, types):
        if typ == 'image_array':
            image_key = key
            break

    session = TubSession(
        path=path, tub=tub, records=records, image_key=image_key
    )
    session.inputs = inputs
    session.types = types
    _sessions[path] = session
    return session


def get_session(path: str) -> TubSession:
    path = _normalize_path(path)
    if path not in _sessions:
        return open_tub(path)
    return _sessions[path]


def list_images(
    path: str,
    offset: int = 0,
    limit: int = 50,
) -> Dict[str, Any]:
    session = get_session(path)
    total = len(session.records)
    slice_ = session.records[offset: offset + limit]
    items = []
    for rec in slice_:
        items.append({
            'index': rec.get('_index'),
            'image_file': rec.get(session.image_key),
            'angle': rec.get('user/angle'),
            'throttle': rec.get('user/throttle'),
        })
    return {
        'path': session.path,
        'total': total,
        'offset': offset,
        'limit': limit,
        'image_key': session.image_key,
        'images': items,
    }


def _record_by_index(session: TubSession, index: int) -> Dict[str, Any]:
    for rec in session.records:
        if rec.get('_index') == index:
            return rec
    raise KeyError(f'No record with _index={index} in tub {session.path}')


def image_path_for_index(path: str, index: int) -> str:
    session = get_session(path)
    rec = _record_by_index(session, index)
    rel = rec.get(session.image_key)
    if not rel:
        raise KeyError(f'Record {index} has no image field {session.image_key}')
    full = os.path.join(session.path, Tub.images(), rel)
    if not os.path.isfile(full):
        raise FileNotFoundError(f'Image file missing: {full}')
    return full


def load_image_array(path: str, index: int) -> np.ndarray:
    """Load tub image as uint8 RGB numpy array (native resolution)."""
    full = image_path_for_index(path, index)
    img = Image.open(full).convert('RGB')
    return np.asarray(img, dtype=np.uint8)


def encode_image(
    arr: np.ndarray,
    fmt: str = 'JPEG',
    quality: int = 85,
    max_size: Optional[Tuple[int, int]] = None,
) -> bytes:
    """Encode numpy RGB array to image bytes. Optionally downscale for thumbs."""
    img = Image.fromarray(np.asarray(arr, dtype=np.uint8))
    if max_size is not None:
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    save_kwargs = {}
    if fmt.upper() in ('JPEG', 'JPG'):
        fmt = 'JPEG'
        save_kwargs['quality'] = quality
    img.save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()
