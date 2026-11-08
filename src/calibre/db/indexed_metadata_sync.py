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
