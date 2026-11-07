#!/usr/bin/env python3
# License: GPLv3
"""Experimental Indexed Library configuration.

An indexed library is represented by a LOCAL directory containing
indexed-library.json and (eventually) metadata.db. The source ebook roots
may be remote. This module deliberately does not open or create databases,
scan roots, or change any ebook files.

Configuration detection is wired into startup; activation remains blocked.
"""

import json
import os
from pathlib import Path

CONFIG_FILENAME = 'indexed-library.json'
CONFIG_VERSION = 1
MODE = 'indexed'


class InvalidIndexedLibraryConfig(ValueError):
    pass


def load_indexed_library_config(library_directory: str | os.PathLike[str]) -> dict:
    """Read an explicitly configured indexed library; never infer from a NAS path.

    Returns a validated configuration. Missing configuration returns None,
    allowing existing managed-library startup to remain the default.
    """
    config_path = Path(library_directory) / CONFIG_FILENAME
    if not config_path.is_file():
        return None
    try:
        config = json.loads(config_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as err:
        raise InvalidIndexedLibraryConfig(f'Cannot read {config_path}: {err}') from err
    if not isinstance(config, dict):
        raise InvalidIndexedLibraryConfig('Indexed library configuration must be an object')
    if config.get('version') != CONFIG_VERSION or config.get('mode') != MODE:
        raise InvalidIndexedLibraryConfig('Unsupported indexed library mode or configuration version')
    roots = config.get('source_roots')
    if not isinstance(roots, list) or not roots or any(
        not isinstance(root, str) or not root.strip() or not os.path.isabs(root)
        for root in roots
    ):
        raise InvalidIndexedLibraryConfig('source_roots must contain absolute filesystem paths')
    # Do not check root existence: NAS volumes can be temporarily offline.
    # Database location is fixed inside the local library directory and
    # is intentionally not configurable from this JSON document.
    return {'version': CONFIG_VERSION, 'mode': MODE, 'source_roots': roots}


def indexed_database_path(library_directory: str | os.PathLike[str]) -> Path:
    """Resolve a configured Indexed library's LOCAL metadata database path.

    This function performs no I/O on the source roots and does not create the
    database or its parent directory. A missing or invalid marker is an error.
    """
    library = Path(library_directory).expanduser().resolve()
    config = load_indexed_library_config(library)
    if config is None:
        raise InvalidIndexedLibraryConfig('Not an Indexed library')
    return library / 'metadata.db'


def check_indexed_library_startup(library_directory: str | os.PathLike[str]) -> None:
    """Fail closed for Indexed libraries until file-operation guards exist.

    Managed libraries return normally. No database or ebook files are opened.
    """
    config = load_indexed_library_config(library_directory)
    if config is None:
        return
    dbpath = indexed_database_path(library_directory)
    if not dbpath.is_absolute():
        raise RuntimeError('Indexed database path must be absolute')
    raise RuntimeError(
        'Indexed Library Mode is not yet available: external file '
        'safety protections must be completed before opening this library'
    )
