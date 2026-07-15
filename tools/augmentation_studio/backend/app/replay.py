"""Registry-backed tub replay inference with an atomic disk cache."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

import donkeycar as dk
from donkeycar.config import Config
from donkeycar.pipeline.types import TubDataset
from donkeycar.utils import normalize_image

from . import apply as apply_mod
from . import tub_loader


_APP_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MODELS_PATH = _APP_ROOT / 'config' / 'replay_models.json'
_DEFAULT_TUBS_PATH = _APP_ROOT / 'config' / 'tubs.json'
_DEFAULT_CACHE_DIR = _APP_ROOT / 'cache'
_SAFE_ID = re.compile(r'^[A-Za-z0-9_.-]+$')
_locks_guard = threading.Lock()
_cache_locks: Dict[str, threading.Lock] = {}


def _configured_path(env_name: str, default: Path) -> Path:
    return Path(os.path.expanduser(os.environ.get(env_name, str(default)))).resolve()


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f'Replay registry not found: {path}')
    with path.open('r', encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f'Replay registry must contain a JSON object: {path}')
    return data


def _load_registries() -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    models_path = _configured_path('LOK_REPLAY_MODELS_PATH', _DEFAULT_MODELS_PATH)
    tubs_path = _configured_path('LOK_REPLAY_TUBS_PATH', _DEFAULT_TUBS_PATH)
    model_data = _read_json(models_path)
    tub_data = _read_json(tubs_path)

    models = model_data.get('models', [])
    tubs = tub_data.get('tubs', {})
    if not isinstance(models, list) or not isinstance(tubs, dict):
        raise ValueError('Replay registries require "models" list and "tubs" object')

    seen = set()
    for model in models:
        if not isinstance(model, dict):
            raise ValueError('Each replay model entry must be an object')
        model_id = model.get('id')
        if not isinstance(model_id, str) or not _SAFE_ID.fullmatch(model_id):
            raise ValueError(f'Invalid replay model id: {model_id!r}')
        if model_id in seen:
            raise ValueError(f'Duplicate replay model id: {model_id}')
        seen.add(model_id)
        for key in ('path', 'type', 'config_path'):
            if not model.get(key):
                raise ValueError(f'Replay model {model_id!r} is missing {key!r}')

    for tub_id, entry in tubs.items():
        if not _SAFE_ID.fullmatch(tub_id) or not isinstance(entry, dict):
            raise ValueError(f'Invalid replay tub entry: {tub_id!r}')
        if not entry.get('path'):
            raise ValueError(f'Replay tub {tub_id!r} is missing "path"')
        if entry.get('tag') not in ('train', 'holdout'):
            raise ValueError(
                f'Replay tub {tub_id!r} tag must be "train" or "holdout"'
            )
    return models, tubs


def list_options() -> Dict[str, Any]:
    """Return registry choices without exposing config implementation details."""
    models, tubs = _load_registries()
    return {
        'models': [
            {
                'id': model['id'],
                'label': model.get('label', model['id']),
                'path': str(Path(model['path']).expanduser().resolve()),
            }
            for model in models
        ],
        'tubs': [
            {
                'id': tub_id,
                'label': entry.get('label', tub_id),
                'path': str(Path(entry['path']).expanduser().resolve()),
                'tag': entry['tag'],
            }
            for tub_id, entry in tubs.items()
        ],
    }


def _resolve_entries(
    tub_id: str, model_selector: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    models, tubs = _load_registries()
    tub_entry = tubs.get(tub_id)
    if tub_entry is None:
        raise KeyError(f'Unknown replay tub: {tub_id}')

    selector_path = str(Path(model_selector).expanduser().resolve())
    model_entry = next(
        (
            model
            for model in models
            if model['id'] == model_selector
            or str(Path(model['path']).expanduser().resolve()) == selector_path
        ),
        None,
    )
    if model_entry is None:
        raise KeyError(f'Unknown or unregistered replay model: {model_selector}')
    return model_entry, tub_entry


def _add_path_metadata(digest: Any, path_value: str) -> None:
    path = Path(os.path.expanduser(path_value)).resolve()
    digest.update(str(path).encode('utf-8'))
    if not path.exists():
        raise FileNotFoundError(f'Replay input not found: {path}')
    if path.is_file():
        stat = path.stat()
        digest.update(f'{stat.st_size}:{stat.st_mtime_ns}'.encode('ascii'))
        return

    for child in sorted(item for item in path.rglob('*') if item.is_file()):
        stat = child.stat()
        digest.update(str(child.relative_to(path)).encode('utf-8'))
        digest.update(f'{stat.st_size}:{stat.st_mtime_ns}'.encode('ascii'))


def _cache_path(
    tub_id: str, model_entry: Dict[str, Any], tub_entry: Dict[str, Any]
) -> Path:
    digest = hashlib.sha256()
    digest.update(model_entry['type'].encode('utf-8'))
    _add_path_metadata(digest, model_entry['path'])
    _add_path_metadata(digest, model_entry['config_path'])
    myconfig_path = model_entry.get('myconfig_path')
    if myconfig_path:
        _add_path_metadata(digest, myconfig_path)
    tub_path = Path(os.path.expanduser(tub_entry['path'])).resolve()
    _add_path_metadata(digest, str(tub_path / 'manifest.json'))
    cache_dir = _configured_path('LOK_REPLAY_CACHE_DIR', _DEFAULT_CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f'replay_{tub_id}_{digest.hexdigest()[:16]}.json'


def _load_config(model_entry: Dict[str, Any]) -> Config:
    config_path = Path(os.path.expanduser(model_entry['config_path'])).resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f'DonkeyCar config not found: {config_path}')
    cfg = Config()
    cfg.from_pyfile(str(config_path))
    myconfig_value = model_entry.get('myconfig_path')
    if myconfig_value:
        myconfig_path = Path(os.path.expanduser(myconfig_value)).resolve()
        if not myconfig_path.is_file():
            raise FileNotFoundError(f'DonkeyCar myconfig not found: {myconfig_path}')
        personal_cfg = Config()
        personal_cfg.from_pyfile(str(myconfig_path))
        cfg.from_object(personal_cfg)
    return cfg


def _as_float(value: Any, field: str, frame_id: Any) -> float:
    if value is None:
        raise ValueError(f'Record {frame_id} is missing {field}')
    array = np.asarray(value)
    if array.size == 0:
        raise ValueError(f'Record {frame_id} has an empty {field}')
    return float(array.reshape(-1)[0])


def _target_record(record: Any) -> Any:
    return record[-1] if isinstance(record, list) else record


def _run_inference(
    model_entry: Dict[str, Any], tub_entry: Dict[str, Any]
) -> List[Dict[str, Any]]:
    cfg = _load_config(model_entry)
    # Replay evaluates every non-deleted record, independent of a training filter.
    cfg.TRAIN_FILTER = None
    # A processor is record-specific (for REGION_MASK), so never cache its output
    # on overlapping TubRecord sequences.
    cfg.CACHE_POLICY = 'NOCACHE'
    model = dk.utils.get_model_by_type(model_entry['type'], cfg)
    model.load(str(Path(model_entry['path']).expanduser().resolve()))

    tub_path = str(Path(tub_entry['path']).expanduser().resolve())
    session = tub_loader.open_tub(tub_path)
    dataset = TubDataset(
        config=cfg, tub_paths=[tub_path], seq_size=model.seq_size()
    )
    results: List[Dict[str, Any]] = []
    try:
        for record in dataset.get_records():
            target = _target_record(record)
            underlying = target.underlying
            frame_id = underlying.get('_index')
            source_records = record if isinstance(record, list) else [record]
            source_indexes = iter(
                item.underlying.get('_index') for item in source_records
            )

            def processor(image: Any) -> np.ndarray:
                source_index = next(source_indexes, frame_id)
                processed = apply_mod.apply_pipeline(
                    np.asarray(image),
                    cfg,
                    record_index=source_index,
                    apply_aug=False,
                )
                return normalize_image(processed)

            input_dict = model.x_transform(record, processor)
            outputs = model.inference_from_dict(input_dict)
            if not isinstance(outputs, (tuple, list)) or len(outputs) < 2:
                raise ValueError(
                    f'Model {model_entry["id"]!r} did not return angle/throttle'
                )
            results.append({
                'frame_id': int(frame_id),
                'actual_angle': _as_float(
                    underlying.get('user/angle'), 'user/angle', frame_id
                ),
                'actual_throttle': _as_float(
                    underlying.get('user/throttle'), 'user/throttle', frame_id
                ),
                'pred_angle': _as_float(outputs[0], 'predicted angle', frame_id),
                'pred_throttle': _as_float(
                    outputs[1], 'predicted throttle', frame_id
                ),
                'image_path': underlying.get(session.image_key),
            })
    finally:
        dataset.close()
    return results


def _lock_for(cache_path: Path) -> threading.Lock:
    key = str(cache_path)
    with _locks_guard:
        return _cache_locks.setdefault(key, threading.Lock())


def _read_cache(path: Path) -> List[Dict[str, Any]]:
    with path.open('r', encoding='utf-8') as handle:
        records = json.load(handle)
    if not isinstance(records, list):
        raise ValueError(f'Invalid replay cache contents: {path}')
    return records


def _write_cache(path: Path, records: List[Dict[str, Any]]) -> None:
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=path.parent,
            prefix=f'.{path.name}.',
            suffix='.tmp',
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(records, handle, separators=(',', ':'))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def get_replay(tub_id: str, model_selector: str) -> Dict[str, Any]:
    """Return cached predictions, running inference once per fingerprint."""
    model_entry, tub_entry = _resolve_entries(tub_id, model_selector)
    cache_path = _cache_path(tub_id, model_entry, tub_entry)
    cache_hit = cache_path.is_file()
    if cache_hit:
        records = _read_cache(cache_path)
    else:
        with _lock_for(cache_path):
            cache_hit = cache_path.is_file()
            if cache_hit:
                records = _read_cache(cache_path)
            else:
                records = _run_inference(model_entry, tub_entry)
                _write_cache(cache_path, records)

    tub_path = str(Path(tub_entry['path']).expanduser().resolve())
    tag = tub_entry['tag']
    return {
        'tub_id': tub_id,
        'tub_path': tub_path,
        'model_id': model_entry['id'],
        'model_label': model_entry.get('label', model_entry['id']),
        'tag': tag,
        'training_warning': tag == 'train',
        'cache_hit': cache_hit,
        'records': records,
    }
