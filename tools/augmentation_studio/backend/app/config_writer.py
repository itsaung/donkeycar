"""Safely patch myconfig.py in place (line-based, with backup).

Rules:
- Never rewrite the whole file: only touch lines whose key matches.
- Prefer the last *active* assignment (later assignments win in Python);
  otherwise un-comment the first commented-out template line;
  otherwise append the key at the end of the file.
- Multi-line exports (e.g. TRAIN_FILTER glue code) live in a managed
  sentinel block that is replaced wholesale on every apply.
- Always write a `<file>.bak` backup before modifying, and write
  atomically (temp file + os.replace) so a crash can't corrupt config.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from typing import Dict, List, Optional, Tuple

BLOCK_BEGIN = '# >>> LOK managed block — do not edit by hand >>>'
BLOCK_END = '# <<< LOK managed block <<<'
# Legacy markers from the previous Tub Studio name — still stripped on apply.
_LEGACY_BLOCK_BEGIN = '# >>> tub-studio managed block — do not edit by hand >>>'
_LEGACY_BLOCK_END = '# <<< tub-studio managed block <<<'


def _normalize(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _key_patterns(key: str) -> Tuple[re.Pattern, re.Pattern]:
    """Active and commented-out assignment patterns for a config key.

    Handles `KEY=1`, `KEY = 1`, `  KEY = 1`, and `# KEY = 1` template lines.
    """
    escaped = re.escape(key)
    active = re.compile(rf'^(\s*){escaped}\s*=')
    commented = re.compile(rf'^(\s*)#\s*{escaped}\s*=')
    return active, commented


_TRAILING_COMMENT = re.compile(r"^[^#'\"]*?(\s+#.*)$")


def _render_line(indent: str, key: str, value_repr: str,
                 old_line: Optional[str] = None) -> str:
    """Build the replacement line, keeping a trailing comment when it is
    unambiguous (no quotes before the `#`)."""
    comment = ''
    if old_line is not None:
        m = _TRAILING_COMMENT.match(old_line)
        if m:
            comment = m.group(1)
    return f'{indent}{key} = {value_repr}{comment}'


def _strip_managed_block(lines: List[str]) -> List[str]:
    markers = [
        (BLOCK_BEGIN, BLOCK_END),
        (_LEGACY_BLOCK_BEGIN, _LEGACY_BLOCK_END),
    ]
    out: List[str] = []
    in_block = False
    active_end = ''
    for line in lines:
        stripped = line.strip()
        if not in_block:
            for begin, end in markers:
                if stripped == begin:
                    in_block = True
                    active_end = end
                    break
            if in_block:
                continue
            out.append(line)
            continue
        if stripped == active_end:
            in_block = False
            active_end = ''
            continue
    # Drop trailing blank lines left behind by a removed block.
    while out and out[-1].strip() == '':
        out.pop()
    return out


def apply_settings(
    config_path: str,
    settings: Dict[str, str],
    raw_blocks: Optional[List[str]] = None,
) -> Dict[str, object]:
    """Patch `settings` (key -> already-formatted value string) into the
    config file. `raw_blocks` are multi-line python snippets placed in the
    managed sentinel block. Returns a summary of what changed."""
    path = _normalize(config_path)
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f'myconfig not found: {path} — create the file first '
            '(e.g. `donkey createcar`) or fix the path.'
        )

    with open(path, 'r', encoding='utf-8') as f:
        original = f.read()
    lines = original.splitlines()

    # Managed block is regenerated from scratch each apply.
    lines = _strip_managed_block(lines)

    updated: List[str] = []
    added: List[str] = []

    for key, value_repr in settings.items():
        active_re, commented_re = _key_patterns(key)

        active_idx = [i for i, ln in enumerate(lines) if active_re.match(ln)]
        if active_idx:
            # Patch the last active assignment: it is the one Python honors.
            i = active_idx[-1]
            indent = active_re.match(lines[i]).group(1)
            lines[i] = _render_line(indent, key, value_repr, lines[i])
            updated.append(key)
            continue

        commented_idx = [
            i for i, ln in enumerate(lines) if commented_re.match(ln)
        ]
        if commented_idx:
            # Un-comment the template line in place.
            i = commented_idx[0]
            indent = commented_re.match(lines[i]).group(1)
            lines[i] = _render_line(indent, key, value_repr)
            updated.append(key)
            continue

        added.append(key)

    if added:
        if lines and lines[-1].strip() != '':
            lines.append('')
        lines.append('# --- LOK: added settings ---')
        for key in added:
            lines.append(f'{key} = {settings[key]}')

    blocks = [b.rstrip('\n') for b in (raw_blocks or []) if b.strip()]
    if blocks:
        if lines and lines[-1].strip() != '':
            lines.append('')
        lines.append(BLOCK_BEGIN)
        for block in blocks:
            lines.extend(block.splitlines())
        lines.append(BLOCK_END)

    new_content = '\n'.join(lines) + '\n'

    backup_path = path + '.bak'
    shutil.copy2(path, backup_path)

    # Atomic replace so a crash mid-write can't leave a corrupt config.
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(path), prefix='.myconfig-', suffix='.tmp'
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return {
        'path': path,
        'backup_path': backup_path,
        'updated': updated,
        'added': added,
        'blocks_replaced': len(blocks),
        'changed': new_content != original,
    }
