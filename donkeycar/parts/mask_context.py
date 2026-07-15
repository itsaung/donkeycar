"""Thread-local record index for per-frame REGION_MASK application."""

from __future__ import annotations

import threading
from typing import Optional

_local = threading.local()


def set_record_index(index: Optional[int]) -> None:
    _local.index = index


def get_record_index() -> Optional[int]:
    return getattr(_local, 'index', None)


def clear_record_index() -> None:
    if hasattr(_local, 'index'):
        delattr(_local, 'index')
