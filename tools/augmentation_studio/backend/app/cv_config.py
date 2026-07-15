"""CV-control configuration import, preview, and export helpers."""

from __future__ import annotations

import ast
import os
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

from donkeycar.config import Config
from donkeycar.parts.image_transformations import ImageTransformations

from . import tub_loader
from .transforms import ROI_DEFAULTS


CV_DEFAULTS: Dict[str, Any] = {
    'CV_PREPROCESS': [],
    'CV_DEBUG_TRANSFORMATIONS': ['RGB2GRAY', 'BLUR', 'CANNY'],
    'CV_SHOW_DEBUG_PIPELINE': False,
    'CANNY_LOW_THRESHOLD': 60,
    'CANNY_HIGH_THRESHOLD': 110,
    'CANNY_APERTURE': 3,
    'BLUR_KERNEL': 5,
    'BLUR_KERNEL_Y': None,
    'BLUR_GAUSSIAN': True,
}
CV_PARAM_KEYS = [
    'CANNY_LOW_THRESHOLD',
    'CANNY_HIGH_THRESHOLD',
    'CANNY_APERTURE',
    'BLUR_KERNEL',
    'BLUR_KERNEL_Y',
    'BLUR_GAUSSIAN',
    'CV_SHOW_DEBUG_PIPELINE',
]
IMPORT_KEYS = set(CV_DEFAULTS) | set(ROI_DEFAULTS) | {
    'MASK_METADATA_PATH',
    'MASK_PRESET',
}


def _normalize(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _literal_assignments(source: str, keys: Iterable[str]) -> Dict[str, Any]:
    """Read literal top-level assignments without executing myconfig.py."""
    allowed = set(keys)
    values: Dict[str, Any] = {}
    tree = ast.parse(source)
    for node in tree.body:
        targets: List[ast.expr] = []
        value_node: Optional[ast.expr] = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value_node = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value_node = node.value
        if value_node is None:
            continue
        names = [
            target.id for target in targets
            if isinstance(target, ast.Name) and target.id in allowed
        ]
        if not names:
            continue
        try:
            value = ast.literal_eval(value_node)
        except (ValueError, TypeError):
            continue
        for name in names:
            values[name] = value
    return values


def load_myconfig(path: str) -> Dict[str, Any]:
    """Import LOK-supported CV values from myconfig.py, without executing it."""
    normalized = _normalize(path)
    if not os.path.isfile(normalized):
        raise FileNotFoundError(f'myconfig not found: {normalized}')
    with open(normalized, 'r', encoding='utf-8') as handle:
        values = _literal_assignments(handle.read(), IMPORT_KEYS)

    roi = dict(ROI_DEFAULTS)
    roi.update({
        key: int(value)
        for key, value in values.items()
        if key in ROI_DEFAULTS
    })
    cv_params = {
        key: values.get(key, CV_DEFAULTS[key])
        for key in CV_PARAM_KEYS
    }
    return {
        'path': normalized,
        'cv_preprocess': list(values.get(
            'CV_PREPROCESS', CV_DEFAULTS['CV_PREPROCESS']
        )),
        'cv_debug_transformations': list(values.get(
            'CV_DEBUG_TRANSFORMATIONS',
            CV_DEFAULTS['CV_DEBUG_TRANSFORMATIONS'],
        )),
        'cv_params': cv_params,
        'roi': roi,
        'mask_metadata_path': values.get('MASK_METADATA_PATH'),
        'mask_preset': values.get('MASK_PRESET'),
    }


def build_cv_config(
    *,
    cv_preprocess: Optional[List[str]] = None,
    cv_debug_transformations: Optional[List[str]] = None,
    cv_params: Optional[Dict[str, Any]] = None,
    roi: Optional[Dict[str, Any]] = None,
) -> Config:
    cfg = Config()
    for key, value in ROI_DEFAULTS.items():
        setattr(cfg, key, value)
    for key, value in CV_DEFAULTS.items():
        setattr(cfg, key, value)
    for key, value in (roi or {}).items():
        if key in ROI_DEFAULTS:
            setattr(cfg, key, int(value))
    cfg.CV_PREPROCESS = list(cv_preprocess or [])
    cfg.CV_DEBUG_TRANSFORMATIONS = list(
        cv_debug_transformations
        if cv_debug_transformations is not None
        else CV_DEFAULTS['CV_DEBUG_TRANSFORMATIONS']
    )
    for key, value in (cv_params or {}).items():
        if key in CV_PARAM_KEYS:
            setattr(cfg, key, value)
    return cfg


def preview_indexes(
    path: str,
    indexes: List[int],
    *,
    cv_preprocess: List[str],
    cv_debug_transformations: List[str],
    cv_params: Dict[str, Any],
    roi: Dict[str, Any],
) -> List[Dict[str, Any]]:
    cfg = build_cv_config(
        cv_preprocess=cv_preprocess,
        cv_debug_transformations=cv_debug_transformations,
        cv_params=cv_params,
        roi=roi,
    )
    preprocess = (
        ImageTransformations(cfg, 'CV_PREPROCESS')
        if cfg.CV_PREPROCESS else None
    )
    debug = (
        ImageTransformations(cfg, 'CV_DEBUG_TRANSFORMATIONS')
        if cfg.CV_DEBUG_TRANSFORMATIONS else None
    )
    results = []
    for index in indexes:
        original = tub_loader.load_image_array(path, index)
        preprocessed = preprocess.run(original) if preprocess else original
        edges = debug.run(preprocessed) if debug else preprocessed
        results.append({
            'index': index,
            'original': np.asarray(original),
            'preprocessed': np.asarray(preprocessed),
            'edges': np.asarray(edges),
        })
    return results
