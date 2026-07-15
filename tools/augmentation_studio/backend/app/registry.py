"""Thin wrappers over donkeycar.pipeline.augmentations registry."""

from __future__ import annotations

from typing import Any, Dict, List

from donkeycar.pipeline.augmentations import (
    AUGMENTATION_REGISTRY,
    TRAINING_AUG_PROB,
)


def list_augmentations() -> Dict[str, Any]:
    """Return registry metadata for the API, including training probability."""
    items: List[Dict[str, Any]] = []
    for name, meta in AUGMENTATION_REGISTRY.items():
        params = []
        for param_name, spec in meta.get('params', {}).items():
            params.append({
                'name': param_name,
                'type': spec.get('type', 'float'),
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
        'augmentations': items,
        'training_prob': TRAINING_AUG_PROB,
        'config_key': 'AUGMENTATIONS',
    }
