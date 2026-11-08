#!/usr/bin/env python3
# License: GPLv3
"""Read-only discovery of files in an Indexed Library source root."""

from __future__ import annotations

import os
import stat as stat_module
from pathlib import Path
from typing import Any, Callable


def scan_indexed_source_roots(
    source_roots: list[str] | tuple[str, ...],
    supported_formats: set[str] | frozenset[str],
    *,
    metadata_reader: Callable[[Any, str], Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Discover regular ebook files and extract metadata without modifying them.

    Directory and file symlinks are skipped. Unreadable files remain in the
    result with an error so discovery is auditable and can be retried.
    """
    formats = {str(fmt).lower().strip().lstrip('.') for fmt in supported_formats}
    formats.discard('')
    if not formats:
        raise ValueError('At least one supported format is required')
    if not source_roots:
        raise ValueError('At least one source root is required')

    if metadata_reader is None:
        from calibre.customize.ui import get_file_type_metadata
        metadata_reader = get_file_type_metadata

    result: dict[str, list[dict[str, Any]]] = {
        'files': [], 'errors': [], 'skipped': [],
    }
    seen: set[tuple[int, int]] = set()

    def visit(path: Path, root: Path) -> None:
        try:
            st = path.stat(follow_symlinks=False)
        except OSError as err:
            result['errors'].append({'file_path': str(path), 'error': str(err)})
            return
        if path.is_symlink():
            result['skipped'].append({'file_path': str(path), 'reason': 'symbolic link'})
            return
        identity = (st.st_dev, st.st_ino)
        if identity in seen:
            result['skipped'].append({'file_path': str(path), 'reason': 'already visited'})
            return
        if path.is_dir():
            seen.add(identity)
            try:
                entries = sorted(os.scandir(path), key=lambda entry: entry.name.casefold())
            except OSError as err:
                result['errors'].append({'file_path': str(path), 'error': str(err)})
                return
            for entry in entries:
                visit(Path(entry.path), root)
            return
        if not stat_module.S_ISREG(st.st_mode):
            result['skipped'].append({'file_path': str(path), 'reason': 'not a regular file'})
            return
        fmt = path.suffix.lower().lstrip('.')
        if fmt not in formats:
            return
        record: dict[str, Any] = {
            'file_path': str(path),
            'relative_path': str(path.relative_to(root)),
            'format': fmt.upper(),
            'file_size': st.st_size,
            'modified_time_ns': st.st_mtime_ns,
            'metadata': None,
        }
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            opened = os.fstat(fd)
            if not stat_module.S_ISREG(opened.st_mode) or (
                opened.st_dev, opened.st_ino
            ) != (st.st_dev, st.st_ino):
                os.close(fd)
                raise OSError('Source file changed during discovery')
            record['file_size'] = opened.st_size
            record['modified_time_ns'] = opened.st_mtime_ns
            with os.fdopen(fd, 'rb') as stream:
                record['metadata'] = metadata_reader(stream, fmt)
        except Exception as err:
            record['error'] = str(err)
            result['errors'].append({
                'file_path': record['file_path'], 'format': record['format'],
                'error': str(err),
            })
        result['files'].append(record)

    for raw_root in source_roots:
        root_input = Path(raw_root).expanduser()
        if not root_input.is_absolute():
            raise ValueError('Source roots must be absolute paths')
        if root_input.is_symlink():
            result['errors'].append({
                'file_path': str(root_input), 'error': 'Source root is a symbolic link',
            })
            continue
        try:
            root = root_input.resolve(strict=True)
            if not root.is_dir():
                raise NotADirectoryError(str(root))
        except OSError as err:
            result['errors'].append({'file_path': str(root_input), 'error': str(err)})
            continue
        seen.clear()
        visit(root, root)

    result['files'].sort(key=lambda item: item['file_path'].casefold())
    return result
