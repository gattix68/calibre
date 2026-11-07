#!/usr/bin/env python3
# License: GPLv3
"""Read-only discovery of ebook files beneath configured source roots.

The walker never follows symbolic links, never opens ebook contents, and
never mutates source files. Per-root and per-entry I/O failures are reported.
"""
import os
import stat
from pathlib import Path

from calibre.ebooks import BOOK_EXTENSIONS


SUPPORTED_EXTENSIONS = frozenset(x.lower().lstrip('.') for x in BOOK_EXTENSIONS)


def discover_ebook_files(source_roots, *, supported_extensions=None):
    """Return (files, errors) from configured roots without following symlinks.

    Each file record contains path, format, size, and modified_time_ns.
    Missing/offline roots are reported and do not stop discovery of other roots.
    Directory and file symlinks are skipped. Hard links are ordinary files.
    """
    extensions = SUPPORTED_EXTENSIONS if supported_extensions is None else frozenset(
        x.lower().lstrip('.') for x in supported_extensions
    )
    files, errors = [], []
    seen_paths = set()

    if not isinstance(source_roots, (list, tuple)) or not source_roots:
        raise ValueError('At least one source root is required')

    for raw_root in source_roots:
        if not isinstance(raw_root, (str, os.PathLike)) or not os.path.isabs(os.fspath(raw_root)):
            raise ValueError('Source roots must be absolute filesystem paths')
        root = Path(raw_root)
        try:
            root_stat = root.lstat()
            if stat.S_ISLNK(root_stat.st_mode):
                errors.append({'root': str(root), 'error': 'Source root is a symbolic link'})
                continue
            if not stat.S_ISDIR(root_stat.st_mode):
                errors.append({'root': str(root), 'error': 'Source root is not a directory'})
                continue
        except OSError as err:
            errors.append({'root': str(root), 'error': str(err)})
            continue

        stack = [root]
        while stack:
            directory = stack.pop()
            try:
                with os.scandir(directory) as entries:
                    # Sorting makes output deterministic across runs.
                    children = sorted(entries, key=lambda e: e.name.casefold(), reverse=True)
            except OSError as err:
                errors.append({'path': str(directory), 'error': str(err)})
                continue

            for entry in children:
                path = Path(entry.path)
                try:
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        stack.append(path)
                        continue
                    if not stat.S_ISREG(info.st_mode):
                        continue
                    suffix = path.suffix.lower().lstrip('.')
                    if suffix not in extensions:
                        continue
                    normalized = os.path.normpath(str(path))
                    if normalized in seen_paths:
                        continue
                    seen_paths.add(normalized)
                    files.append({
                        'path': normalized,
                        'format': suffix,
                        'size': info.st_size,
                        'modified_time_ns': info.st_mtime_ns,
                    })
                except OSError as err:
                    errors.append({'path': str(path), 'error': str(err)})

    files.sort(key=lambda item: (item['path'].casefold(), item['format']))
    errors.sort(key=lambda item: (item.get('root', item.get('path', '')).casefold(), item['error']))
    return files, errors
