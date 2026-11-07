#!/usr/bin/env python3
# License: GPLv3
"""Read-only, fail-closed completion verification for Indexed Libraries.

Does not activate Indexed Mode, scan sources, or modify any files.
"""
import os
import fcntl
import stat
from pathlib import Path

from calibre.db.indexed_database_recovery import (
    IncompleteIndexedDatabase, inspect_indexed_database,
)
from calibre.db.indexed_library_config import (
    CONFIG_FILENAME, load_indexed_library_config, validate_indexed_storage_separation,
)
from calibre.db.indexed_storage_validation import require_local_indexed_storage

COMPLETION_FILENAME = 'indexed-library.complete'
COMPLETION_SIGNATURE = b'indexed-library-complete-v1\n'


def verify_indexed_library_complete(library_directory):
    """Return the verified local database path; otherwise fail closed.

    Source roots may be offline. Neither source paths nor files are opened.
    """
    raw = Path(library_directory).expanduser()
    if raw.is_symlink():
        raise IncompleteIndexedDatabase('Indexed library directory is a symbolic link')
    library = raw.resolve(strict=True)
    require_local_indexed_storage(library)
    # Do not accept a completion marker while a cooperating creator is
    # still publishing it. Advisory locking cannot prevent hostile writers
    # or prove success after an abrupt process termination.
    directory_fd = os.open(library, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(directory_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IncompleteIndexedDatabase(
                'Indexed library creation is still in progress'
            ) from exc
        return _verify_unlocked(library)
    finally:
        os.close(directory_fd)


def _verify_unlocked(library):
    if not library.is_dir():
        raise IncompleteIndexedDatabase('Indexed library directory is missing')
    marker = library / CONFIG_FILENAME
    completion = library / COMPLETION_FILENAME
    for path in (marker, completion):
        if path.is_symlink():
            raise IncompleteIndexedDatabase('Indexed library marker is a symbolic link')
        try:
            mode = path.stat(follow_symlinks=False).st_mode
        except FileNotFoundError as exc:
            raise IncompleteIndexedDatabase('Indexed library creation is incomplete') from exc
        if not stat.S_ISREG(mode):
            raise IncompleteIndexedDatabase('Indexed library marker is not a regular file')
    if load_indexed_library_config(library) is None:
        raise IncompleteIndexedDatabase('Indexed configuration missing')
    validate_indexed_storage_separation(library)
    with completion.open('rb') as handle:
        if handle.read(len(COMPLETION_SIGNATURE) + 1) != COMPLETION_SIGNATURE:
            raise IncompleteIndexedDatabase('Indexed completion signature invalid')
    expected = {CONFIG_FILENAME, COMPLETION_FILENAME, 'metadata.db'}
    if set(os.listdir(library)) != expected:
        raise IncompleteIndexedDatabase('Unexpected files in Indexed library directory')
    return inspect_indexed_database(library)
