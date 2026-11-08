#!/usr/bin/env python3
# License: GPLv3
"""Read embedded metadata from an Indexed Library format without sidecars."""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any, Callable


def read_embedded_metadata(
    file_path: str,
    fmt: str,
    *,
    metadata_reader: Callable[[Any, str], Any] | None = None,
) -> Any:
    """Read metadata embedded in *file_path* using Calibre's format handler.

    The file is opened read-only. This intentionally calls the format-specific
    metadata reader directly rather than the higher-level get_metadata()
    helper, which can merge filename-derived and metadata.opf sidecar values.
    """
    normalized = fmt.lower().strip().lstrip('.')
    if not normalized:
        raise ValueError('A non-empty format is required')

    path = os.path.abspath(file_path)
    if os.path.islink(path) or not os.path.isfile(path):
        raise OSError(f'Indexed format is missing or is not a regular file: {path}')
    if os.path.splitext(path)[1].lower() != '.' + normalized:
        raise ValueError('Format must match the external file extension')

    if metadata_reader is None:
        from calibre.customize.ui import get_file_type_metadata

        metadata_reader = get_file_type_metadata

    with open(path, 'rb') as stream:
        return metadata_reader(stream, normalized)


# These are standard Calibre metadata fields that commonly have embedded
# representations. Fields absent from a format's metadata are not considered
# changes and therefore cannot erase existing Calibre values.
COMPARABLE_METADATA_FIELDS = (
    'title', 'authors', 'author_sort', 'title_sort', 'series', 'series_index',
    'publisher', 'pubdate', 'tags', 'comments', 'languages', 'identifiers',
    'rating',
)


def _metadata_value(metadata: Any, field: str) -> Any:
    """Return a field value, treating Calibre's null marker as unavailable."""
    try:
        if metadata.is_null(field):
            return None
    except (AttributeError, KeyError, TypeError):
        pass
    try:
        return metadata.get(field, None)
    except (AttributeError, TypeError):
        return getattr(metadata, field, None)


def _comparable_value(value: Any) -> Any:
    """Normalize common metadata containers and date values for comparison."""
    if value is None:
        return None
    if hasattr(value, 'isoformat') and callable(value.isoformat):
        return value.isoformat()
    if isinstance(value, dict):
        return tuple(sorted((str(k).casefold(), _comparable_value(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple, set)):
        values = [_comparable_value(v) for v in value]
        return tuple(sorted(values, key=repr)) if isinstance(value, set) else tuple(values)
    if isinstance(value, str):
        return value.strip()
    return value


def compare_metadata(
    database_metadata: Any,
    embedded_metadata: Any,
    fields: tuple[str, ...] = COMPARABLE_METADATA_FIELDS,
) -> dict[str, dict[str, Any]]:
    """Return embedded, non-null fields that differ from the database.

    This function is deliberately read-only. Missing/null embedded fields are
    ignored, so sparse formats cannot clear richer Calibre database metadata.
    Returned values are the original values, not normalized representations.
    """
    differences = {}
    for field in fields:
        embedded_value = _metadata_value(embedded_metadata, field)
        if embedded_value is None:
            continue
        database_value = _metadata_value(database_metadata, field)
        if _comparable_value(database_value) != _comparable_value(embedded_value):
            differences[field] = {
                'database': database_value,
                'embedded': embedded_value,
            }
    return differences


def merge_embedded_metadata(database_metadata: Any, embedded_metadata: Any) -> tuple[Any, dict[str, dict[str, Any]]]:
    """Return a cloned database Metadata object with external differences applied.

    The original database object and embedded metadata object are never
    modified. The caller remains responsible for persisting the returned
    Metadata object through Calibre's normal database API.
    """
    differences = compare_metadata(database_metadata, embedded_metadata)
    if not differences:
        return database_metadata.deepcopy(), {}
    updated = database_metadata.deepcopy()
    for field, change in differences.items():
        setattr(updated, field, change['embedded'])
    return updated, differences


def indexed_file_has_changed(recorded_size: int, recorded_mtime_ns: int, current_stat: Any) -> bool:
    """Return whether the file size or nanosecond mtime differs from its index."""
    return (
        int(recorded_size) != int(current_stat.st_size)
        or int(recorded_mtime_ns) != int(current_stat.st_mtime_ns)
    )


def plan_embedded_metadata_sync(database_metadata: Any, embedded_by_format: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    """Build a conflict-aware metadata update from all changed formats of a book.

    A field is eligible for update only when all changed formats that provide
    a non-null value agree. Conflicting fields are reported and left unchanged.
    The database Metadata object is cloned; no input object is modified.
    """
    candidates: dict[str, list[tuple[str, Any]]] = {}
    for fmt, embedded in sorted(embedded_by_format.items(), key=lambda item: item[0].casefold()):
        for field, change in compare_metadata(database_metadata, embedded).items():
            candidates.setdefault(field, []).append((fmt, change['embedded']))

    updates: dict[str, Any] = {}
    conflicts: dict[str, list[dict[str, Any]]] = {}
    for field, values in candidates.items():
        distinct: dict[Any, list[str]] = {}
        for fmt, value in values:
            key = repr(_comparable_value(value))
            distinct.setdefault(key, []).append(fmt)
        if len(distinct) > 1:
            conflicts[field] = [
                {'formats': formats, 'value': next(value for fmt, value in values if fmt in formats)}
                for formats in distinct.values()
            ]
        else:
            updates[field] = values[0][1]

    updated = database_metadata.deepcopy()
    for field, value in updates.items():
        setattr(updated, field, value)
    return updated, {'updates': updates, 'conflicts': conflicts}


def apply_to_indexed_file_atomically(file_path: str, transform: Callable[[Any], Any]) -> Any:
    """Transform a temporary copy and atomically replace the same source path.

    The source must remain the same regular, non-symlink file throughout the
    operation. Failed transforms leave the original bytes untouched.
    """
    path = os.path.abspath(file_path)
    if os.path.islink(path) or not os.path.isfile(path):
        raise OSError(f'Indexed source file is missing or unsafe: {path}')
    before = os.stat(path, follow_symlinks=False)
    fd, temporary_path = tempfile.mkstemp(
        prefix='.calibre-indexed-', suffix=os.path.splitext(path)[1],
        dir=os.path.dirname(path),
    )
    try:
        with os.fdopen(fd, 'w+b') as target, open(path, 'rb') as source:
            shutil.copyfileobj(source, target)
            target.flush()
            target.seek(0)
            answer = transform(target)
            target.flush()
            os.fsync(target.fileno())
        current = os.stat(path, follow_symlinks=False)
        if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
        ):
            raise RuntimeError('Indexed source file changed during metadata update')
        os.replace(temporary_path, path)
        return answer
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.remove(temporary_path)
        except OSError:
            pass
        raise
