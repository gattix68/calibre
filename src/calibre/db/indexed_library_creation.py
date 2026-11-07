#!/usr/bin/env python3
# License: GPLv3
"""Pure, non-mutating preflight for explicit Indexed Library creation.

No directory creation, NAS access, database writes or Calibre GUI imports.
"""
import os
from pathlib import Path

from calibre.db.indexed_storage_validation import require_local_indexed_storage


class InvalidIndexedCreation(ValueError):
    pass


def validate_indexed_creation(library_directory, source_roots):
    """Return normalized paths for an EXISTING empty local destination.

    Offline source roots are permitted. This is preflight only: initialization
    must independently revalidate and must never trust this result as a lock.
    """
    raw_library = Path(library_directory).expanduser()
    if raw_library.is_symlink():
        raise InvalidIndexedCreation('Library directory must not be a symbolic link')
    library = raw_library.resolve(strict=True)
    if not library.is_dir():
        raise InvalidIndexedCreation('Library destination must be a directory')
    if any(library.iterdir()):
        raise InvalidIndexedCreation('Library destination must be empty')
    require_local_indexed_storage(library)
    if not isinstance(source_roots, (list, tuple)) or not source_roots:
        raise InvalidIndexedCreation('At least one source root is required')
    normalized = []
    for root in source_roots:
        if not isinstance(root, (str, os.PathLike)) or not os.path.isabs(os.fspath(root)):
            raise InvalidIndexedCreation('Source roots must be absolute paths')
        source = Path(root).resolve(strict=False)
        if os.path.commonpath((str(library), str(source))) in (str(library), str(source)):
            raise InvalidIndexedCreation('Source root overlaps the local database directory')
        if str(source) not in normalized:
            normalized.append(str(source))
    identity = library.stat(follow_symlinks=False)
    return {'library_directory': str(library), 'source_roots': normalized,
            'destination_identity': (identity.st_dev, identity.st_ino)}
