"""Region mask metadata loading and application (blocks out regions)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from donkeycar.parts import mask_context

logger = logging.getLogger(__name__)


def load_mask_metadata(path: str) -> Dict[str, Any]:
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return {
            'version': 1,
            'presets': {},
            'by_index': {},
            'default_preset': None,
        }
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    data.setdefault('version', 1)
    data.setdefault('presets', {})
    data.setdefault('by_index', {})
    data.setdefault('default_preset', None)
    return data


def regions_for_index(
    meta: Dict[str, Any],
    index: Optional[int],
    preset: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Resolve regions: per-index overrides, else named/default preset."""
    if index is not None:
        by_index = meta.get('by_index') or {}
        key = str(index)
        if key in by_index:
            return list(by_index[key] or [])
    name = preset or meta.get('default_preset')
    if name:
        return list((meta.get('presets') or {}).get(name) or [])
    return []


def apply_regions(image: np.ndarray, regions: List[Dict[str, Any]]) -> np.ndarray:
    """Zero out listed regions (block distracting areas). Returns new array."""
    if image is None or not regions:
        return image
    out = image.copy()
    h, w = out.shape[:2]
    for region in regions:
        rtype = region.get('type', 'rect')
        if rtype == 'rect':
            x = int(region.get('x', 0))
            y = int(region.get('y', 0))
            rw = int(region.get('w', 0))
            rh = int(region.get('h', 0))
            x2 = max(0, min(w, x + rw))
            y2 = max(0, min(h, y + rh))
            x1 = max(0, min(w, x))
            y1 = max(0, min(h, y))
            if x2 > x1 and y2 > y1:
                out[y1:y2, x1:x2] = 0
        elif rtype == 'poly':
            pts = region.get('points') or []
            if len(pts) >= 3:
                poly = np.array(pts, dtype=np.int32)
                mask = np.ones(out.shape[:2], dtype=np.uint8) * 255
                cv2.fillPoly(mask, [poly], 0)
                if out.ndim == 3:
                    mask3 = mask[:, :, None]
                    out = np.where(mask3 == 0, 0, out).astype(out.dtype)
                else:
                    out = np.where(mask == 0, 0, out).astype(out.dtype)
    return out


class ImgRegionMask:
    """
    DonkeyCar image part: block out regions from MASK_METADATA_PATH.

    Uses mask_context record index when set (training/studio); otherwise
    applies default_preset / MASK_PRESET regions.
    """

    def __init__(self, config) -> None:
        self.path = getattr(config, 'MASK_METADATA_PATH', None)
        self.preset = getattr(config, 'MASK_PRESET', None)
        self._meta: Optional[Dict[str, Any]] = None
        self._mtime: Optional[float] = None

    def _load(self) -> Dict[str, Any]:
        if not self.path:
            return {'presets': {}, 'by_index': {}, 'default_preset': None}
        path = os.path.expanduser(self.path)
        try:
            mtime = os.path.getmtime(path) if os.path.isfile(path) else None
        except OSError:
            mtime = None
        if self._meta is None or mtime != self._mtime:
            self._meta = load_mask_metadata(path)
            self._mtime = mtime
        return self._meta

    def run(self, image):
        if image is None:
            return None
        meta = self._load()
        index = mask_context.get_record_index()
        regions = regions_for_index(meta, index, preset=self.preset)
        return apply_regions(image, regions)

    def shutdown(self):
        self._meta = None
        self._mtime = None
