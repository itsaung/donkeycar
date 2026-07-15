"""Format myconfig.py-compatible snippets for LOK."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from donkeycar.pipeline.augmentations import (
    AUGMENTATION_REGISTRY,
    TRAINING_AUG_PROB,
)

from .apply import build_aug_config, build_pipeline_config
from . import curation
from . import cv_config
from . import masks as masks_mod


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, (list, tuple)):
        if isinstance(value, list) and len(value) == 2:
            return f'({value[0]}, {value[1]})'
        if isinstance(value, tuple):
            if len(value) == 1:
                return f'({value[0]},)'
            return f'({", ".join(str(v) for v in value)})'
        return repr(value)
    return repr(value)


def export_snippet(augmentations: List[Dict[str, Any]]) -> str:
    cfg, names = build_aug_config(augmentations)
    lines = [
        '# --- LOK: augmentations ---',
        f'AUGMENTATIONS = {names!r}',
    ]
    emitted = set()
    for name in names:
        for param_name in AUGMENTATION_REGISTRY[name]['params']:
            if param_name in emitted:
                continue
            emitted.add(param_name)
            lines.append(f'{param_name} = {_format_value(getattr(cfg, param_name))}')
    lines.append(
        f'# Training applies each aug with p={TRAINING_AUG_PROB} '
        f'(ImageAugmentation default; not a myconfig key)'
    )
    lines.append('')
    return '\n'.join(lines)


def export_transforms_snippet(
    transformations: List[str],
    post_transformations: List[str],
    roi: Dict[str, Any],
) -> str:
    cfg = build_pipeline_config(
        transformations=transformations,
        post_transformations=post_transformations,
        roi=roi,
    )
    lines = [
        '# --- LOK: transforms / ROI ---',
        f'TRANSFORMATIONS = {list(transformations)!r}',
        f'POST_TRANSFORMATIONS = {list(post_transformations)!r}',
    ]
    keys = sorted({k for k in roi if k.startswith('ROI_')})
    if not keys:
        # emit defaults used by selected transforms
        from donkeycar.parts.image_transformations import TRANSFORM_REGISTRY
        for name in list(transformations) + list(post_transformations):
            if name in TRANSFORM_REGISTRY:
                keys.extend(TRANSFORM_REGISTRY[name]['params'].keys())
        keys = sorted(set(k for k in keys if k.startswith('ROI_')))
    for key in keys:
        lines.append(f'{key} = {int(getattr(cfg, key))}')
    lines.append('')
    return '\n'.join(lines)


def _cv_control_settings(
    cv_preprocess: List[str],
    cv_debug_transformations: List[str],
    cv_params: Dict[str, Any],
    roi: Dict[str, Any],
) -> Dict[str, str]:
    cfg = cv_config.build_cv_config(
        cv_preprocess=cv_preprocess,
        cv_debug_transformations=cv_debug_transformations,
        cv_params=cv_params,
        roi=roi,
    )
    settings = {
        'CV_PREPROCESS': repr(list(cfg.CV_PREPROCESS)),
        'CV_DEBUG_TRANSFORMATIONS': repr(
            list(cfg.CV_DEBUG_TRANSFORMATIONS)
        ),
    }
    for key in cv_config.CV_PARAM_KEYS:
        settings[key] = _format_value(getattr(cfg, key))
    for key in sorted(roi):
        if key.startswith('ROI_'):
            settings[key] = str(int(getattr(cfg, key)))
    return settings


def export_cv_control_snippet(
    cv_preprocess: List[str],
    cv_debug_transformations: List[str],
    cv_params: Dict[str, Any],
    roi: Dict[str, Any],
) -> str:
    lines = ['# --- LOK: cv_control ---']
    for key, value in _cv_control_settings(
        cv_preprocess, cv_debug_transformations, cv_params, roi
    ).items():
        lines.append(f'{key} = {value}')
    lines.append('')
    return '\n'.join(lines)


def _aug_settings(augmentations: List[Dict[str, Any]]) -> Dict[str, str]:
    cfg, names = build_aug_config(augmentations)
    settings: Dict[str, str] = {'AUGMENTATIONS': repr(names)}
    for name in names:
        for param_name in AUGMENTATION_REGISTRY[name]['params']:
            if param_name in settings:
                continue
            settings[param_name] = _format_value(getattr(cfg, param_name))
    return settings


def _transform_settings(
    transformations: List[str],
    post_transformations: List[str],
    roi: Dict[str, Any],
) -> Dict[str, str]:
    cfg = build_pipeline_config(
        transformations=transformations,
        post_transformations=post_transformations,
        roi=roi,
    )
    settings: Dict[str, str] = {
        'TRANSFORMATIONS': repr(list(transformations)),
        'POST_TRANSFORMATIONS': repr(list(post_transformations)),
    }
    keys = sorted({k for k in roi if k.startswith('ROI_')})
    if not keys:
        from donkeycar.parts.image_transformations import TRANSFORM_REGISTRY
        for name in list(transformations) + list(post_transformations):
            if name in TRANSFORM_REGISTRY:
                keys.extend(TRANSFORM_REGISTRY[name]['params'].keys())
        keys = sorted(set(k for k in keys if k.startswith('ROI_')))
    for key in keys:
        settings[key] = str(int(getattr(cfg, key)))
    return settings


def build_full_settings(
    *,
    augmentations: Optional[List[Dict[str, Any]]] = None,
    transformations: Optional[List[str]] = None,
    post_transformations: Optional[List[str]] = None,
    roi: Optional[Dict[str, Any]] = None,
    excludes_path: Optional[str] = None,
    masks_path: Optional[str] = None,
    mask_preset: Optional[str] = None,
    profile: str = 'training',
    cv_preprocess: Optional[List[str]] = None,
    cv_debug_transformations: Optional[List[str]] = None,
    cv_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Same inputs as export_full_snippet, but returns structured output for
    the myconfig writer: {settings: key -> formatted value, raw_blocks: [...]}
    """
    settings: Dict[str, str] = {}
    raw_blocks: List[str] = []

    if profile not in ('training', 'cv_control'):
        raise ValueError(f'Unknown export profile: {profile}')

    if profile == 'cv_control':
        settings.update(_cv_control_settings(
            cv_preprocess or [],
            (
                cv_debug_transformations
                if cv_debug_transformations is not None
                else list(cv_config.CV_DEFAULTS['CV_DEBUG_TRANSFORMATIONS'])
            ),
            cv_params or {},
            roi or {},
        ))
    elif transformations is not None or post_transformations is not None or roi:
        settings.update(_transform_settings(
            transformations or [],
            post_transformations or [],
            roi or {},
        ))

    if masks_path:
        import os
        trans = list(
            cv_preprocess or [] if profile == 'cv_control'
            else transformations or []
        )
        if 'REGION_MASK' not in trans:
            trans.append('REGION_MASK')
        transform_key = (
            'CV_PREPROCESS' if profile == 'cv_control'
            else 'TRANSFORMATIONS'
        )
        settings[transform_key] = repr(trans)
        if profile != 'cv_control' and 'POST_TRANSFORMATIONS' not in settings:
            settings['POST_TRANSFORMATIONS'] = repr(
                list(post_transformations or []))
        settings['MASK_METADATA_PATH'] = repr(
            os.path.abspath(os.path.expanduser(masks_path)))
        if mask_preset:
            settings['MASK_PRESET'] = repr(mask_preset)

    if profile == 'training' and augmentations is not None:
        settings.update(_aug_settings(augmentations))

    if excludes_path:
        # TRAIN_FILTER needs helper code, so it goes in the managed block.
        raw_blocks.append(curation.export_train_filter_snippet(excludes_path))

    return {'settings': settings, 'raw_blocks': raw_blocks}


def export_full_snippet(
    *,
    augmentations: Optional[List[Dict[str, Any]]] = None,
    transformations: Optional[List[str]] = None,
    post_transformations: Optional[List[str]] = None,
    roi: Optional[Dict[str, Any]] = None,
    excludes_path: Optional[str] = None,
    masks_path: Optional[str] = None,
    mask_preset: Optional[str] = None,
    profile: str = 'training',
    cv_preprocess: Optional[List[str]] = None,
    cv_debug_transformations: Optional[List[str]] = None,
    cv_params: Optional[Dict[str, Any]] = None,
) -> str:
    if profile not in ('training', 'cv_control'):
        raise ValueError(f'Unknown export profile: {profile}')
    if profile == 'cv_control':
        built = build_full_settings(
            augmentations=augmentations,
            roi=roi,
            excludes_path=excludes_path,
            masks_path=masks_path,
            mask_preset=mask_preset,
            profile=profile,
            cv_preprocess=cv_preprocess,
            cv_debug_transformations=cv_debug_transformations,
            cv_params=cv_params,
        )
        lines = ['# --- LOK: cv_control ---']
        lines.extend(
            f'{key} = {value}'
            for key, value in built['settings'].items()
        )
        if built['raw_blocks']:
            lines.extend(['', *built['raw_blocks']])
        lines.append('')
        return '\n'.join(lines)

    parts = []
    if transformations is not None or post_transformations is not None or roi:
        parts.append(export_transforms_snippet(
            transformations or [],
            post_transformations or [],
            roi or {},
        ))
    if masks_path:
        parts.append(masks_mod.export_mask_snippet(
            masks_path,
            transformations=transformations,
            post_transformations=post_transformations,
            preset=mask_preset,
        ))
    if augmentations is not None:
        parts.append(export_snippet(augmentations))
    if excludes_path:
        parts.append(curation.export_train_filter_snippet(excludes_path))
    return '\n'.join(parts)
