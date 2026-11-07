#!/usr/bin/env python3
# License: GPLv3
"""Read-only, fail-closed inspection of interrupted Indexed DB creation.

Never deletes or repairs files. Not wired into Calibre startup.
"""
import os
import sqlite3
from pathlib import Path

from calibre.db.indexed_library_config import indexed_database_path
from calibre.db.indexed_storage_validation import require_local_indexed_storage


class IncompleteIndexedDatabase(RuntimeError):
    pass


def inspect_indexed_database(library_directory):
    """Return database path only when basic structural checks pass.

    Any sidecar or incomplete schema requires explicit human review.
    Does not inspect or access ebook source roots.
    """
    library = Path(library_directory).expanduser().resolve()
    require_local_indexed_storage(library)
    dbpath = indexed_database_path(library)
    for suffix in ('-journal', '-wal', '-shm'):
        if os.path.lexists(library / ('metadata.db' + suffix)):
            raise IncompleteIndexedDatabase('SQLite sidecar present; manual review required')
    if not dbpath.is_file() or dbpath.is_symlink():
        raise IncompleteIndexedDatabase('Indexed metadata.db missing or not a regular file')
    try:
        # immutable=1 prevents SQLite from recovering a hot journal or writing.
        uri = dbpath.as_uri() + '?mode=ro&immutable=1'
        with sqlite3.connect(uri, uri=True) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise IncompleteIndexedDatabase('Indexed database integrity check failed')
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if not {'books', 'indexed_files'}.issubset(tables):
                raise IncompleteIndexedDatabase('Indexed schema incomplete')
            if db.execute('PRAGMA user_version').fetchone()[0] != 28:
                raise IncompleteIndexedDatabase('Unexpected Indexed base schema version')
    except sqlite3.DatabaseError as exc:
        raise IncompleteIndexedDatabase('Indexed database cannot be inspected') from exc
    return dbpath
