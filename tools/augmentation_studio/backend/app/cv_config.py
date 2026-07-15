"""CV-control configuration import, preview, and export helpers."""

from __future__ import annotations

import ast
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
from simple_pid import PID

from donkeycar.config import Config
from donkeycar.parts.image_transformations import ImageTransformations
from donkeycar.parts.line_follower import LineFollower

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

# Defaults match donkeycar/templates/cfg_cv_control.py
LINE_FOLLOWER_DEFAULTS: Dict[str, Any] = {
    'SCAN_Y': 100,
    'SCAN_HEIGHT': 20,
    'COLOR_THRESHOLD_LOW': (0, 50, 50),
    'COLOR_THRESHOLD_HIGH': (50, 255, 255),
    'TARGET_PIXEL': None,
    'TARGET_THRESHOLD': 10,
    'CONFIDENCE_THRESHOLD': 0.0015,
    'THROTTLE_MAX': 0.3,
    'THROTTLE_MIN': 0.15,
    'THROTTLE_INITIAL': 0.15,
    'THROTTLE_STEP': 0.05,
    'PID_P': -0.01,
    'PID_I': 0.0,
    'PID_D': -0.0001,
}
LINE_FOLLOWER_KEYS = list(LINE_FOLLOWER_DEFAULTS.keys())
_HSV_TUPLE_KEYS = {'COLOR_THRESHOLD_LOW', 'COLOR_THRESHOLD_HIGH'}

IMPORT_KEYS = (
    set(CV_DEFAULTS)
    | set(ROI_DEFAULTS)
    | set(LINE_FOLLOWER_DEFAULTS)
    | {
        'MASK_METADATA_PATH',
        'MASK_PRESET',
    }
)


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


def _coerce_hsv(value: Any, default: Tuple[int, int, int]) -> Tuple[int, int, int]:
    if value is None:
        return default
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return (int(value[0]), int(value[1]), int(value[2]))
    return default


def _normalize_line_follower(
    line_follower: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw = dict(LINE_FOLLOWER_DEFAULTS)
    if line_follower:
        raw.update(line_follower)
    out: Dict[str, Any] = {}
    for key in LINE_FOLLOWER_KEYS:
        value = raw.get(key, LINE_FOLLOWER_DEFAULTS[key])
        if key in _HSV_TUPLE_KEYS:
            out[key] = _coerce_hsv(value, LINE_FOLLOWER_DEFAULTS[key])
        elif key == 'TARGET_PIXEL':
            out[key] = None if value is None else int(value)
        elif key in (
            'SCAN_Y', 'SCAN_HEIGHT', 'TARGET_THRESHOLD',
        ):
            out[key] = int(value)
        else:
            out[key] = value
    # Keep initial throttle aligned with min when not explicitly distinct.
    if line_follower is None or 'THROTTLE_INITIAL' not in line_follower:
        out['THROTTLE_INITIAL'] = out['THROTTLE_MIN']
    return out


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
    lf_from_file = {
        key: values[key]
        for key in LINE_FOLLOWER_KEYS
        if key in values
    }
    line_follower = _normalize_line_follower(
        lf_from_file if lf_from_file else None
    )
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
        'line_follower': line_follower,
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
    line_follower: Optional[Dict[str, Any]] = None,
) -> Config:
    cfg = Config()
    for key, value in ROI_DEFAULTS.items():
        setattr(cfg, key, value)
    for key, value in CV_DEFAULTS.items():
        setattr(cfg, key, value)
    for key, value in _normalize_line_follower(line_follower).items():
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


def run_line_follower_on_image(
    image: np.ndarray,
    *,
    cfg: Config,
) -> Dict[str, Any]:
    """Run LineFollower once on a single RGB image (lab-stable)."""
    image = np.asarray(image)
    height, width = image.shape[:2]
    cfg.OVERLAY_IMAGE = True

    # Lab stability: never latch TARGET_PIXEL from the first detection.
    target = getattr(cfg, 'TARGET_PIXEL', None)
    if target is None:
        cfg.TARGET_PIXEL = int(width // 2)

    scan_y = int(cfg.SCAN_Y)
    scan_height = int(cfg.SCAN_HEIGHT)
    if scan_y < 0:
        scan_y = 0
    if scan_y >= height:
        scan_y = max(0, height - 1)
    if scan_height < 1:
        scan_height = 1
    if scan_y + scan_height > height:
        scan_height = max(1, height - scan_y)
    cfg.SCAN_Y = scan_y
    cfg.SCAN_HEIGHT = scan_height

    pid = PID(Kp=cfg.PID_P, Ki=cfg.PID_I, Kd=cfg.PID_D)
    controller = LineFollower(pid, cfg)
    max_yellow, confidence, _mask = controller.get_i_color(image)
    outputs = controller.run(image)
    steering = float(outputs[0])
    throttle = float(outputs[1])
    overlay = outputs[2] if len(outputs) > 2 else image
    if overlay is None or overlay is False:
        overlay = image
    line_detected = float(confidence) >= float(cfg.CONFIDENCE_THRESHOLD)
    return {
        'overlay': np.asarray(overlay),
        'max_yellow': int(max_yellow),
        'confidence': float(confidence),
        'steering': steering,
        'throttle': throttle,
        'scan_y': scan_y,
        'scan_height': scan_height,
        'target_pixel': int(controller.target_pixel),
        'line_detected': bool(line_detected),
    }


def preview_line_follower_indexes(
    path: str,
    indexes: List[int],
    *,
    cv_preprocess: List[str],
    roi: Dict[str, Any],
    line_follower: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Preview LineFollower on tub frames (fresh PID per request)."""
    base_cfg = build_cv_config(
        cv_preprocess=cv_preprocess,
        roi=roi,
        line_follower=line_follower,
    )
    preprocess = (
        ImageTransformations(base_cfg, 'CV_PREPROCESS')
        if base_cfg.CV_PREPROCESS else None
    )
    results: List[Dict[str, Any]] = []
    for index in indexes:
        original = tub_loader.load_image_array(path, index)
        preprocessed = preprocess.run(original) if preprocess else original
        # Fresh config + PID per frame so lab previews do not share I-state.
        frame_cfg = build_cv_config(
            cv_preprocess=cv_preprocess,
            roi=roi,
            line_follower=line_follower,
        )
        metrics = run_line_follower_on_image(
            np.asarray(preprocessed), cfg=frame_cfg
        )
        results.append({
            'index': index,
            'original': np.asarray(original),
            'preprocessed': np.asarray(preprocessed),
            'overlay': metrics['overlay'],
            'max_yellow': metrics['max_yellow'],
            'confidence': metrics['confidence'],
            'steering': metrics['steering'],
            'throttle': metrics['throttle'],
            'scan_y': metrics['scan_y'],
            'scan_height': metrics['scan_height'],
            'target_pixel': metrics['target_pixel'],
            'line_detected': metrics['line_detected'],
            'width': int(np.asarray(original).shape[1]),
            'height': int(np.asarray(original).shape[0]),
        })
    return results
