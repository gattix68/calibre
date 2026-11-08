#!/usr/bin/env python3
# License: GPLv3
"""Explicit, offline-safe creation of a NEW Indexed Library database.

This module is not invoked by Calibre startup. Caller supplies the packaged
Calibre base-schema SQL; no source roots are accessed or changed.
"""
import os
import sqlite3
import sys
import uuid
from pathlib import Path

from calibre.db.indexed_storage_validation import require_local_indexed_storage
from calibre.db.indexed_library_config import (
    INDEXED_FILES_SCHEMA, indexed_database_path, validate_indexed_storage_separation,
)


def verify_indexed_destination_identity(library, expected_identity):
    """Recheck mount classification and directory identity before disk I/O."""
    require_local_indexed_storage(library)
    actual = os.stat(library, follow_symlinks=False)
    if (actual.st_dev, actual.st_ino) != expected_identity:
        raise RuntimeError('Indexed database directory changed during initialization')


def initialize_indexed_database(library_directory, base_schema_sql):
    """Create a fresh local metadata.db; never overwrite an existing database.

    The configured library directory must already exist. On initialization
    failure, remove only the new file created by this call.
    """
    library = Path(library_directory).expanduser().resolve()
    if not library.is_dir():
        raise FileNotFoundError(f'Indexed library directory does not exist: {library}')
    validate_indexed_storage_separation(library_directory)
    # Check the actual destination mount before creating any database file.
    require_local_indexed_storage(library)
    initial_stat = os.stat(library, follow_symlinks=False)
    expected_identity = (initial_stat.st_dev, initial_stat.st_ino)
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

    if sys.platform != 'linux' or not os.path.isdir('/proc/self/fd'):
        raise RuntimeError('Descriptor-anchored Indexed initialization requires Linux procfs')

    # Hold a directory descriptor so exclusive creation and cleanup are
    # relative to the same directory, even if its pathname is renamed.
    # Linux-only for now; other platforms remain blocked by storage validation.
    dir_flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    dir_fd = os.open(library, dir_flags)
    try:
        opened = os.fstat(dir_fd)
        if (opened.st_dev, opened.st_ino) != expected_identity:
            raise RuntimeError('Indexed database directory changed during initialization')
        verify_indexed_destination_identity(library, expected_identity)
        fd = os.open('metadata.db', os.O_CREAT | os.O_EXCL | os.O_RDWR |
                     getattr(os, 'O_NOFOLLOW', 0), 0o600, dir_fd=dir_fd)
        created_stat = os.fstat(fd)
        os.close(fd)
        try:
            verify_indexed_destination_identity(library, expected_identity)
            # Anchor SQLite's open to the directory descriptor, not the
            # mutable original library pathname. Linux procfs is required.
            anchored_dbpath = f'/proc/self/fd/{dir_fd}/metadata.db'
            with sqlite3.connect(anchored_dbpath) as db:
                # Refuse if the database pathname no longer refers to the
                # file exclusively created by this initializer.
                current = os.stat('metadata.db', dir_fd=dir_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (created_stat.st_dev, created_stat.st_ino):
                    raise RuntimeError('Indexed database file changed during initialization')
                # Initial creation uses rollback journaling, never WAL sidecars.
                # SQLite owns and removes its transient rollback journal.
                mode = db.execute('PRAGMA journal_mode=DELETE').fetchone()[0]
                if mode.lower() != 'delete':
                    raise RuntimeError('Indexed initialization requires DELETE journal mode')
                db.create_function('title_sort', 1, lambda title: title)
                db.create_function('uuid4', 0, lambda: str(uuid.uuid4()))
                db.executescript(base_schema_sql)
                db.executescript(';\n'.join(INDEXED_FILES_SCHEMA))
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Indexed database integrity check failed')
                if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='indexed_files'"
                ).fetchone() is None:
                    raise RuntimeError('Indexed file mapping table was not created')
            # Ensure the completed SQLite file and its directory entry have
            # reached the filesystem synchronization boundary before the
            # creator is allowed to publish a completion marker.
            sync_fd = os.open('metadata.db', os.O_RDONLY | os.O_NOFOLLOW,
                              dir_fd=dir_fd)
            try:
                synced = os.fstat(sync_fd)
                if (synced.st_dev, synced.st_ino) != (created_stat.st_dev, created_stat.st_ino):
                    raise RuntimeError('Indexed database changed before durable sync')
                os.fsync(sync_fd)
            finally:
                os.close(sync_fd)
            os.fsync(dir_fd)
            verify_indexed_destination_identity(library, expected_identity)
            return dbpath
        except BaseException:
            # Only remove our original file from the opened directory.
            try:
                current = os.stat('metadata.db', dir_fd=dir_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if (current.st_dev, current.st_ino) == (created_stat.st_dev, created_stat.st_ino):
                    os.unlink('metadata.db', dir_fd=dir_fd)
            raise
    finally:
        os.close(dir_fd)
