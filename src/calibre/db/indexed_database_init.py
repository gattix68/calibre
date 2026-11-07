#!/usr/bin/env python3
# License: GPLv3
"""Explicit, offline-safe creation of a NEW Indexed Library database.

This module is not invoked by Calibre startup. Caller supplies the packaged
Calibre base-schema SQL; no source roots are accessed or changed.
"""
import os
import sqlite3
import uuid
from pathlib import Path

from calibre.db.indexed_library_config import (
    INDEXED_FILES_SCHEMA, indexed_database_path,
)


def initialize_indexed_database(library_directory, base_schema_sql):
    """Create a fresh local metadata.db; never overwrite an existing database.

    The configured library directory must already exist. On initialization
    failure, remove only the new file created by this call.
    """
    library = Path(library_directory).expanduser().resolve()
    if not library.is_dir():
        raise FileNotFoundError(f'Indexed library directory does not exist: {library}')
    dbpath = indexed_database_path(library)
    # A new Indexed library must have its own otherwise-empty directory.
    # Refuse to initialize over a Managed library or unrelated user files.
    marker = library / 'indexed-library.json'
    if marker.is_symlink():
        raise ValueError('Indexed library marker must not be a symbolic link')
    unexpected = [entry.name for entry in library.iterdir() if entry.name != marker.name]
    if unexpected:
        raise FileExistsError('Indexed library directory is not empty: ' + ', '.join(sorted(unexpected)))
    if not isinstance(base_schema_sql, str) or not base_schema_sql.strip():
        raise ValueError('Non-empty Calibre base schema SQL is required')

    # O_EXCL prevents replacing an existing database, including on races.
    fd = os.open(dbpath, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    created_stat = os.fstat(fd)
    os.close(fd)
    try:
        with sqlite3.connect(dbpath) as db:
            db.create_function('title_sort', 1, lambda title: title)
            db.create_function('uuid4', 0, lambda: str(uuid.uuid4()))
            db.executescript(base_schema_sql)
            db.executescript(INDEXED_FILES_SCHEMA)
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Indexed database integrity check failed')
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='indexed_files'"
            ).fetchone() is None:
                raise RuntimeError('Indexed file mapping table was not created')
        return dbpath
    except BaseException:
        # No other process should open this new, unpublished library database.
        # Remove only the database created by our exclusive open.
        # Do not remove a different file if another process replaced ours.
        try:
            current = dbpath.stat(follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if (current.st_dev, current.st_ino) == (created_stat.st_dev, created_stat.st_ino):
                dbpath.unlink()
        raise
