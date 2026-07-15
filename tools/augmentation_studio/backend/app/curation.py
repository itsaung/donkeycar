"""Curation sidecars — never write into the tub directory."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Set


def _normalize(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def assert_outside_tub(sidecar_path: str, tub_path: str) -> None:
    side = _normalize(sidecar_path)
    tub = _normalize(tub_path)
    if side == tub or side.startswith(tub + os.sep):
        raise ValueError(
            'Sidecar must be outside the tub directory '
            '(tub must stay byte-for-byte untouched)'
        )


def load_excludes(sidecar_path: str) -> Dict[str, Any]:
    path = _normalize(sidecar_path)
    if not os.path.isfile(path):
        return {
            'version': 1,
            'tub_path': None,
            'excluded_indexes': [],
        }
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    data.setdefault('version', 1)
    data.setdefault('excluded_indexes', [])
    return data


def save_excludes(
    sidecar_path: str,
    tub_path: str,
    excluded_indexes: List[int],
) -> Dict[str, Any]:
    assert_outside_tub(sidecar_path, tub_path)
    path = _normalize(sidecar_path)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    data = {
        'version': 1,
        'tub_path': _normalize(tub_path),
        'excluded_indexes': sorted(set(int(i) for i in excluded_indexes)),
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
    return data


def export_train_filter_snippet(sidecar_path: str) -> str:
    path = _normalize(sidecar_path)
    return (
        '# --- LOK curation export ---\n'
        '# Does NOT use Tub.delete_records (that rewrites manifest.json).\n'
        'import json\n'
        'import os\n'
        f'_STUDIO_EXCLUDES_PATH = {path!r}\n'
        '_EXCLUDED = set()\n'
        'if os.path.isfile(_STUDIO_EXCLUDES_PATH):\n'
        '    with open(_STUDIO_EXCLUDES_PATH) as _f:\n'
        '        _EXCLUDED = set(json.load(_f).get("excluded_indexes", []))\n'
        'TRAIN_FILTER = lambda record: record.underlying.get("_index") '
        'not in _EXCLUDED\n'
    )


def excluded_set(sidecar_path: str) -> Set[int]:
    data = load_excludes(sidecar_path)
    return set(int(i) for i in data.get('excluded_indexes', []))
