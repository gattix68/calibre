#!/usr/bin/env python3
# License: GPLv3
"""Explicit Linux-only Indexed Library creation; not connected to Calibre GUI."""
import json
import os
from pathlib import Path

from calibre.db.indexed_library_config import CONFIG_FILENAME, CONFIG_VERSION, MODE
from calibre.db.indexed_library_creation import validate_indexed_creation
from calibre.db.indexed_database_init import initialize_indexed_database


def create_indexed_library(library_directory, source_roots, base_schema_sql):
    """Create a marker and database in a previously empty local directory.

    Never creates or accesses source directories. On ordinary failures,
    removes only the marker this operation created. The initializer owns
    database cleanup. Interrupted processes require read-only recovery review.
    """
    plan = validate_indexed_creation(library_directory, source_roots)
    library = Path(plan['library_directory'])
    dir_fd = os.open(library, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    marker_stat = None
    try:
        before = os.fstat(dir_fd)
        current = os.stat(library, follow_symlinks=False)
        if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError('Indexed destination changed before creation')
        if os.listdir(dir_fd):
            raise FileExistsError('Indexed destination is no longer empty')
        payload = json.dumps({
            'version': CONFIG_VERSION, 'mode': MODE,
            'source_roots': plan['source_roots'],
        }, indent=2).encode('utf-8') + b'\n'
        fd = os.open(CONFIG_FILENAME, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                     0o600, dir_fd=dir_fd)
        marker_stat = os.fstat(fd)
        try:
            with os.fdopen(fd, 'wb') as marker:
                marker.write(payload)
                marker.flush()
                os.fsync(marker.fileno())
        except BaseException:
            raise
        os.fsync(dir_fd)
        # The initializer independently revalidates local storage and marker.
        dbpath = initialize_indexed_database(library, base_schema_sql)
        return dbpath
    except BaseException:
        if marker_stat is not None:
            try:
                current = os.stat(CONFIG_FILENAME, dir_fd=dir_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if (current.st_dev, current.st_ino) == (marker_stat.st_dev, marker_stat.st_ino):
                    os.unlink(CONFIG_FILENAME, dir_fd=dir_fd)
        raise
    finally:
        os.close(dir_fd)
