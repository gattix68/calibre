#!/usr/bin/env python3
# License: GPLv3
"""Explicit Linux-only Indexed Library creation; not connected to Calibre GUI."""
import json
import os
from pathlib import Path

from calibre.db.indexed_library_config import CONFIG_FILENAME, CONFIG_VERSION, MODE
from calibre.db.indexed_library_creation import validate_indexed_creation
from calibre.db.indexed_database_init import initialize_indexed_database
from calibre.db.indexed_database_recovery import inspect_indexed_database

COMPLETION_FILENAME = 'indexed-library.complete'


def _identity(dir_fd, filename):
    st = os.stat(filename, dir_fd=dir_fd, follow_symlinks=False)
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _check_final_inputs(dir_fd, library, plan, marker_identity, db_identity, payload):
    st = os.stat(library, follow_symlinks=False)
    if (st.st_dev, st.st_ino) != plan['destination_identity']:
        raise RuntimeError('Indexed directory replaced during verification')
    if _identity(dir_fd, CONFIG_FILENAME) != marker_identity:
        raise RuntimeError('Indexed configuration changed during verification')
    if _identity(dir_fd, 'metadata.db') != db_identity:
        raise RuntimeError('Indexed database changed during verification')
    fd = os.open(CONFIG_FILENAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    with os.fdopen(fd, 'rb') as handle:
        if handle.read(len(payload) + 1) != payload:
            raise RuntimeError('Indexed configuration contents changed')


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
    completion_stat = None
    try:
        before = os.fstat(dir_fd)
        current = os.stat(library, follow_symlinks=False)
        if ((before.st_dev, before.st_ino) != (current.st_dev, current.st_ino)
                or (before.st_dev, before.st_ino) != plan['destination_identity']):
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
        # An interrupted operation cannot publish the completion sentinel.
        marker_identity = _identity(dir_fd, CONFIG_FILENAME)
        db_identity = _identity(dir_fd, 'metadata.db')
        _check_final_inputs(dir_fd, library, plan, marker_identity, db_identity, payload)
        inspect_indexed_database(library)
        _check_final_inputs(dir_fd, library, plan, marker_identity, db_identity, payload)
        if set(os.listdir(dir_fd)) != {CONFIG_FILENAME, 'metadata.db'}:
            raise RuntimeError('Unexpected files appeared during Indexed creation')
        completion_fd = os.open(
            COMPLETION_FILENAME, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
            0o600, dir_fd=dir_fd,
        )
        completion_stat = os.fstat(completion_fd)
        with os.fdopen(completion_fd, 'wb') as completion:
            completion.write(b'indexed-library-complete-v1\n')
            completion.flush()
            os.fsync(completion.fileno())
        os.fsync(dir_fd)
        # Detect changes made while the completion marker was being written.
        _check_final_inputs(dir_fd, library, plan, marker_identity, db_identity, payload)
        if set(os.listdir(dir_fd)) != {CONFIG_FILENAME, 'metadata.db', COMPLETION_FILENAME}:
            raise RuntimeError('Indexed directory changed during completion publication')
        return dbpath
    except BaseException:
        # If publication fails, remove only the completion file created by
        # this operation. Leave configuration/database for recovery review.
        if completion_stat is not None:
            try:
                published = os.stat(COMPLETION_FILENAME, dir_fd=dir_fd,
                                    follow_symlinks=False)
                if (published.st_dev, published.st_ino) == (completion_stat.st_dev, completion_stat.st_ino):
                    os.unlink(COMPLETION_FILENAME, dir_fd=dir_fd)
                    os.fsync(dir_fd)
            except FileNotFoundError:
                pass
        # Preserve the marker if a database exists, so interrupted creations
        # remain identifiable and are never mistaken for Managed libraries.
        if marker_stat is not None and set(os.listdir(dir_fd)) == {CONFIG_FILENAME}:
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
