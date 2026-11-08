#!/usr/bin/env python
# License: GPLv3
"""Resolve an explicitly configured local database path for a managed library.

This is an opt-in, low-level path resolver, not a second library format.
The books root remains Calibre's normal library_path.
"""
import json
import os
import tempfile

CONFIG_NAME = '.calibre-separated-storage.json'


def resolve_database_path(library_path: str) -> str:
    """Return the configured metadata.db path, or the standard Calibre path.

    A missing books root is an error for a configured split library: never
    silently initialize a new empty library on an unmounted NAS.
    """
    root = os.path.abspath(library_path)
    default = os.path.join(root, 'metadata.db')
    config_path = os.path.join(root, CONFIG_NAME)
    if not os.path.isfile(config_path):
        return default
    if not os.path.isdir(root):
        raise FileNotFoundError(f'Books root is unavailable: {root}')
    with open(config_path, encoding='utf-8') as stream:
        config = json.load(stream)
    if not isinstance(config, dict) or config.get('version') != 1:
        raise ValueError('Unsupported separated-library configuration')
    database_dir = config.get('database_directory')
    if not isinstance(database_dir, str) or not os.path.isabs(database_dir):
        raise ValueError('Database directory must be an absolute path')
    database_dir = os.path.realpath(database_dir)
    if not os.path.isdir(database_dir):
        raise FileNotFoundError(f'Local database directory is unavailable: {database_dir}')
    if os.path.samefile(database_dir, root):
        raise ValueError('Separated database directory must differ from books root')
    if os.path.exists(default):
        raise FileExistsError('Books root already contains metadata.db; refusing ambiguous database selection')
    if not os.access(database_dir, os.W_OK):
        raise PermissionError(f'Database directory is not writable: {database_dir}')
    return os.path.join(database_dir, 'metadata.db')


def configure_separated_storage(library_path: str, database_directory: str) -> str:
    """Atomically configure a *new* normal library before DB initialization.

    Both directories must already exist. Never relocate an existing database.
    Returns the target database path; the caller can then initialize Calibre.
    """
    root = os.path.abspath(library_path)
    database_directory = os.path.abspath(database_directory)
    if not os.path.isdir(root):
        raise FileNotFoundError(f'Books root is unavailable: {root}')
    if not os.path.isdir(database_directory):
        raise FileNotFoundError(f'Database directory is unavailable: {database_directory}')
    if os.path.samefile(root, database_directory):
        raise ValueError('Database and books directories must differ')
    if os.path.exists(os.path.join(root, 'metadata.db')):
        raise FileExistsError('Cannot configure an existing standard Calibre library')
    config_path = os.path.join(root, CONFIG_NAME)
    if os.path.lexists(config_path):
        raise FileExistsError(f'Storage configuration already exists: {config_path}')
    target = os.path.join(os.path.realpath(database_directory), 'metadata.db')
    if os.path.exists(target):
        raise FileExistsError(f'Database target already exists: {target}')
    if not os.access(database_directory, os.W_OK) or not os.access(root, os.W_OK):
        raise PermissionError('Both storage directories must be writable')
    # Use an exclusive create: concurrent attempts cannot overwrite a marker.
    # The marker is written only after all validation has succeeded.
    payload = json.dumps({'version': 1, 'database_directory': os.path.realpath(database_directory)}, indent=2)
    fd, temporary = tempfile.mkstemp(prefix='.calibre-storage-', dir=root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(payload + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        # A hard link fails rather than replacing an existing marker.
        os.link(temporary, config_path)
    finally:
        os.unlink(temporary)
    return target
