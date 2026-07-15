"""Mask sidecars — never write into the tub directory."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from donkeycar.parts.region_mask import load_mask_metadata

from . import curation


def load_masks(sidecar_path: str) -> Dict[str, Any]:
    return load_mask_metadata(sidecar_path)


def save_masks(
    sidecar_path: str,
    tub_path: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    curation.assert_outside_tub(sidecar_path, tub_path)
    path = os.path.abspath(os.path.expanduser(sidecar_path))
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    out = {
        'version': int(data.get('version', 1)),
        'tub_path': os.path.abspath(os.path.expanduser(tub_path)),
        'presets': data.get('presets') or {},
        'by_index': data.get('by_index') or {},
        'default_preset': data.get('default_preset'),
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2)
        f.write('\n')
    return out


def export_mask_snippet(
    sidecar_path: str,
    transformations: Optional[List[str]] = None,
    post_transformations: Optional[List[str]] = None,
    preset: Optional[str] = None,
) -> str:
    path = os.path.abspath(os.path.expanduser(sidecar_path))
    trans = list(transformations or [])
    if 'REGION_MASK' not in trans:
        trans.append('REGION_MASK')
    lines = [
        '# --- LOK mask export ---',
        f'TRANSFORMATIONS = {trans!r}',
    ]
    if post_transformations is not None:
        lines.append(f'POST_TRANSFORMATIONS = {list(post_transformations)!r}')
    lines.append(f'MASK_METADATA_PATH = {path!r}')
    if preset:
        lines.append(f'MASK_PRESET = {preset!r}')
    lines.append(
        '# Per-index regions apply when training sets mask_context '
        '(BatchSequence); originals stay untouched.'
    )
    lines.append('')
    return '\n'.join(lines)
