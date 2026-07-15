"""Offline replay for cv_control-compatible controllers."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from simple_pid import PID

from donkeycar.config import Config
from donkeycar.parts import mask_context
from donkeycar.parts.image_transformations import ImageTransformations

from . import tub_loader


_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_CONFIG = (
    _REPO_ROOT / 'donkeycar' / 'templates' / 'cfg_cv_control.py'
)


def _load_config(myconfig_path: Optional[str]) -> Config:
    cfg = Config()
    cfg.from_pyfile(str(_DEFAULT_CONFIG))
    if myconfig_path:
        path = Path(os.path.expanduser(myconfig_path)).resolve()
        if not path.is_file():
            raise FileNotFoundError(f'myconfig not found: {path}')
        personal = Config()
        personal.from_pyfile(str(path))
        cfg.from_object(personal)
    return cfg


def _number(record: Dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        value = record.get(key)
        if value is not None:
            array = np.asarray(value)
            if array.size:
                return float(array.reshape(-1)[0])
    return default


def run_replay(
    tub_path: str,
    myconfig_path: Optional[str] = None,
    controller_module: Optional[str] = None,
    controller_class: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = _load_config(myconfig_path)
    module_name = controller_module or cfg.CV_CONTROLLER_MODULE
    class_name = controller_class or cfg.CV_CONTROLLER_CLASS
    module = importlib.import_module(module_name)
    controller_type = getattr(module, class_name)
    pid = PID(Kp=cfg.PID_P, Ki=cfg.PID_I, Kd=cfg.PID_D)
    controller = controller_type(pid, cfg)

    preprocess_names = list(getattr(cfg, 'CV_PREPROCESS', None) or [])
    preprocess = (
        ImageTransformations(cfg, 'CV_PREPROCESS')
        if preprocess_names else None
    )
    session = tub_loader.open_tub(tub_path)
    records: List[Dict[str, Any]] = []
    for record in session.records:
        frame_id = record.get('_index')
        if frame_id is None:
            continue
        image = tub_loader.load_image_array(session.path, int(frame_id))
        mask_context.set_record_index(int(frame_id))
        try:
            controller_image = preprocess.run(image) if preprocess else image
            outputs = controller.run(controller_image)
        finally:
            mask_context.clear_record_index()
        if not isinstance(outputs, (tuple, list)) or len(outputs) < 2:
            raise ValueError(
                f'{module_name}.{class_name}.run() must return '
                'steering and throttle'
            )
        records.append({
            'frame_id': int(frame_id),
            'actual_angle': _number(
                record, 'user/angle', 'user/steering', 'steering'
            ),
            'actual_throttle': _number(
                record, 'user/throttle', 'throttle'
            ),
            'pred_angle': _number(
                {'value': outputs[0]}, 'value'
            ),
            'pred_throttle': _number(
                {'value': outputs[1]}, 'value'
            ),
            'image_path': record.get(session.image_key),
        })

    label = f'{module_name}.{class_name}'
    return {
        'tub_id': Path(session.path).name,
        'tub_path': session.path,
        'model_id': label,
        'model_label': label,
        'tag': 'holdout',
        'training_warning': False,
        'cache_hit': False,
        'records': records,
    }
