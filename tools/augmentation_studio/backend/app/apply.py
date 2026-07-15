"""Apply real DonkeyCar pipeline parts for LOK preview."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from donkeycar.config import Config
from donkeycar.parts import mask_context
from donkeycar.parts.image_transformations import (
    TRANSFORM_REGISTRY,
    ImageTransformations,
)
from donkeycar.pipeline.augmentations import (
    AUGMENTATION_REGISTRY,
    ImageAugmentation,
)

from donkeycar.parts.region_mask import apply_regions, regions_for_index

from . import tub_loader
from .transforms import ROI_DEFAULTS

ParamValue = Union[float, int, str, Sequence[float]]


def _apply_inline_masks(
    img: np.ndarray,
    index: Optional[int],
    mask_data: Optional[Dict[str, Any]],
    mask_preset: Optional[str],
) -> np.ndarray:
    if not mask_data:
        return img
    regions = regions_for_index(mask_data, index, preset=mask_preset)
    return apply_regions(img, regions)


def build_aug_config(
    augmentations: List[Dict[str, Any]],
) -> Tuple[Config, List[str]]:
    cfg = Config()
    names: List[str] = []
    for item in augmentations:
        name = item.get('name')
        if not name:
            raise ValueError('Each augmentation requires a name')
        if name not in AUGMENTATION_REGISTRY:
            known = ', '.join(sorted(AUGMENTATION_REGISTRY.keys()))
            raise ValueError(f"Unknown augmentation '{name}'. Known: {known}")
        names.append(name)
        params = item.get('params') or {}
        spec = AUGMENTATION_REGISTRY[name]['params']
        for param_name, param_spec in spec.items():
            if param_name in params:
                value = _coerce_param(params[param_name], param_spec)
            else:
                value = param_spec['default']
            setattr(cfg, param_name, value)
    cfg.AUGMENTATIONS = names
    return cfg, names


# Back-compat alias used by export.py
build_config = build_aug_config


def _coerce_param(value: Any, param_spec: Dict[str, Any]) -> ParamValue:
    ptype = param_spec.get('type', 'float')
    if ptype == 'float_or_tuple':
        if isinstance(value, (list, tuple)):
            if len(value) != 2:
                raise ValueError(f'Expected 2-tuple, got {value}')
            return (float(value[0]), float(value[1]))
        return float(value)
    if ptype == 'float':
        return float(value)
    if ptype == 'int':
        return int(value)
    if ptype == 'str':
        return str(value)
    return value


def build_pipeline_config(
    *,
    augmentations: Optional[List[Dict[str, Any]]] = None,
    transformations: Optional[List[str]] = None,
    post_transformations: Optional[List[str]] = None,
    roi: Optional[Dict[str, Any]] = None,
    mask_metadata_path: Optional[str] = None,
    mask_preset: Optional[str] = None,
) -> Config:
    cfg = Config()
    for k, v in ROI_DEFAULTS.items():
        setattr(cfg, k, v)
    if roi:
        for k, v in roi.items():
            if k.startswith('ROI_'):
                setattr(cfg, k, int(v))
    cfg.TRANSFORMATIONS = list(transformations or [])
    cfg.POST_TRANSFORMATIONS = list(post_transformations or [])
    if mask_metadata_path:
        cfg.MASK_METADATA_PATH = mask_metadata_path
    if mask_preset:
        cfg.MASK_PRESET = mask_preset

    if augmentations:
        aug_cfg, names = build_aug_config(augmentations)
        cfg.AUGMENTATIONS = names
        for name in names:
            for param_name in AUGMENTATION_REGISTRY[name]['params']:
                setattr(cfg, param_name, getattr(aug_cfg, param_name))
    else:
        cfg.AUGMENTATIONS = []
    return cfg


def apply_pipeline(
    img_arr: np.ndarray,
    cfg: Config,
    *,
    record_index: Optional[int] = None,
    aug_prob: float = 1.0,
    apply_aug: bool = True,
    inline_mask_data: Optional[Dict[str, Any]] = None,
) -> np.ndarray:
    """Match training: TRANSFORMATIONS → AUGMENTATIONS → POST_TRANSFORMATIONS."""
    mask_context.set_record_index(record_index)
    try:
        img = img_arr
        # Live LOK override: apply in-memory regions before/with REGION_MASK
        if inline_mask_data is not None:
            img = _apply_inline_masks(
                img, record_index, inline_mask_data,
                getattr(cfg, 'MASK_PRESET', None),
            )
        if getattr(cfg, 'TRANSFORMATIONS', None):
            # Skip REGION_MASK part if we already applied inline (avoid double)
            names = list(cfg.TRANSFORMATIONS)
            if inline_mask_data is not None:
                names = [n for n in names if n != 'REGION_MASK']
                if names:
                    cfg2 = Config()
                    for attr in dir(cfg):
                        if attr.isupper():
                            setattr(cfg2, attr, getattr(cfg, attr))
                    cfg2.TRANSFORMATIONS = names
                    img = ImageTransformations(cfg2, 'TRANSFORMATIONS').run(img)
            else:
                img = ImageTransformations(cfg, 'TRANSFORMATIONS').run(img)
        if apply_aug and getattr(cfg, 'AUGMENTATIONS', None):
            img = ImageAugmentation(cfg, 'AUGMENTATIONS', prob=aug_prob).run(img)
        if getattr(cfg, 'POST_TRANSFORMATIONS', None):
            img = ImageTransformations(cfg, 'POST_TRANSFORMATIONS').run(img)
        return img
    finally:
        mask_context.clear_record_index()


def apply_augmentations(
    img_arr: np.ndarray,
    augmentations: List[Dict[str, Any]],
    prob: float = 1.0,
) -> np.ndarray:
    if not augmentations:
        return img_arr
    cfg, _ = build_aug_config(augmentations)
    return ImageAugmentation(cfg, 'AUGMENTATIONS', prob=prob).run(img_arr)


def preview_indexes(
    path: str,
    indexes: List[int],
    augmentations: List[Dict[str, Any]],
    prob: float = 1.0,
    *,
    transformations: Optional[List[str]] = None,
    post_transformations: Optional[List[str]] = None,
    roi: Optional[Dict[str, Any]] = None,
    mask_metadata_path: Optional[str] = None,
    mask_preset: Optional[str] = None,
    apply_aug: bool = True,
    mask_data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    cfg = build_pipeline_config(
        augmentations=augmentations,
        transformations=transformations,
        post_transformations=post_transformations,
        roi=roi,
        mask_metadata_path=mask_metadata_path,
        mask_preset=mask_preset,
    )
    results = []
    for index in indexes:
        original = tub_loader.load_image_array(path, index)
        processed = apply_pipeline(
            original,
            cfg,
            record_index=index,
            aug_prob=prob,
            apply_aug=apply_aug,
            inline_mask_data=mask_data,
        )
        results.append({
            'index': index,
            'original': original,
            'augmented': processed,
        })
    return results
