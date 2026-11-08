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
    # Only genuine absence is Managed Mode. Broken or nonregular markers
    # may indicate interrupted creation and must fail closed.
    if not os.path.lexists(config_path):
        return None
    if config_path.is_symlink() or not config_path.is_file():
        raise InvalidIndexedLibraryConfig(
            'Indexed library marker exists but is not a regular file'
        )
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



def validate_indexed_storage_separation(library_directory: str | os.PathLike[str]) -> None:
    """Reject obvious database/source overlap; not a network filesystem detector.

    Does not probe source-root availability, so offline NAS paths are allowed.
    Full local-volume verification is required before enabling GUI creation.
    """
    library_input = Path(library_directory).expanduser()
    if library_input.is_symlink():
        raise InvalidIndexedLibraryConfig('Indexed library directory must not be a symbolic link')
    library = library_input.resolve()
    config = load_indexed_library_config(library)
    if config is None:
        raise InvalidIndexedLibraryConfig('Not an Indexed library')
    for root in config['source_roots']:
        source = Path(root).expanduser().resolve(strict=False)
        try:
            common = os.path.commonpath((str(library), str(source)))
        except ValueError:  # Different drives on Windows
            continue
        if common == str(library) or common == str(source):
            raise InvalidIndexedLibraryConfig(
                'Indexed database directory must not contain or be inside an ebook source root'
            )


def check_indexed_library_startup(library_directory: str | os.PathLike[str]) -> None:
    """Validate a completed Indexed Library before normal Calibre startup.

    Managed libraries return normally. Indexed libraries must have the
    explicit completion sentinel and the external-file mapping schema.
    """
    config = load_indexed_library_config(library_directory)
    if config is None:
        return
    dbpath = indexed_database_path(library_directory)
    if not dbpath.is_absolute() or not dbpath.is_file():
        raise RuntimeError('Indexed Library database is missing or invalid')
    completion = Path(library_directory) / 'indexed-library.complete'
    if completion.is_symlink() or not completion.is_file():
        raise RuntimeError('Indexed Library creation is incomplete; completion marker is missing')
    if completion.read_bytes() != b'indexed-library-complete-v1\\n':
        raise RuntimeError('Indexed Library completion marker is invalid')
    import sqlite3
    try:
        with sqlite3.connect(f'file:{dbpath}?mode=ro', uri=True) as conn:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if not {'books', 'data', 'formats', 'indexed_files'} <= tables:
                raise RuntimeError('Indexed Library database schema is incomplete')
    except sqlite3.Error as err:
        raise RuntimeError(f'Cannot validate Indexed Library database: {err}') from err


# Indexed-only extension. Never include this in the managed schema or its
# automatic migration chain. Activation remains blocked by the startup guard.
INDEXED_FILES_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS indexed_files (
        book_id INTEGER NOT NULL,
        format TEXT NOT NULL COLLATE NOCASE,
        file_path TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        modified_time_ns INTEGER NOT NULL,
        device_id INTEGER,
        inode INTEGER,
        PRIMARY KEY (book_id, format),
        FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS indexed_files_book_deleted
        AFTER DELETE ON books
        BEGIN
            DELETE FROM indexed_files WHERE book_id = OLD.id;
        END
    """,
)
