"""Transform registry + ROI config helpers for LOK."""

from __future__ import annotations

from typing import Any, Dict, List

from donkeycar.parts.image_transformations import TRANSFORM_REGISTRY


ROI_DEFAULTS = {
    'ROI_CROP_LEFT': 0,
    'ROI_CROP_TOP': 45,
    'ROI_CROP_RIGHT': 0,
    'ROI_CROP_BOTTOM': 0,
    'ROI_TRAPEZE_UL': 20,
    'ROI_TRAPEZE_UR': 140,
    'ROI_TRAPEZE_LL': 0,
    'ROI_TRAPEZE_LR': 160,
    'ROI_TRAPEZE_MIN_Y': 60,
    'ROI_TRAPEZE_MAX_Y': 120,
}


def list_transforms() -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for name, meta in TRANSFORM_REGISTRY.items():
        params = []
        for param_name, spec in meta.get('params', {}).items():
            params.append({
                'name': param_name,
                'type': spec.get('type', 'int'),
                'default': spec.get('default'),
                'min': spec.get('min'),
                'max': spec.get('max'),
                'step': spec.get('step'),
                'description': spec.get('description', ''),
            })
        items.append({
            'name': name,
            'description': meta.get('description', ''),
            'params': params,
        })
    return {
        'transforms': items,
        'config_keys': ['TRANSFORMATIONS', 'POST_TRANSFORMATIONS'],
        'roi_defaults': dict(ROI_DEFAULTS),
    }
