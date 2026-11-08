#!/usr/bin/env python3
# License: GPLv3
"""Read embedded metadata from an Indexed Library format without sidecars."""

from __future__ import annotations

import os
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
