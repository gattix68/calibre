#!/usr/bin/env python
# License: GPLv3
"""Resolve an explicitly configured local database path for a managed library.

This is an opt-in, low-level path resolver, not a second library format.
The books root remains Calibre's normal library_path.
"""
import json
import os
import uuid

CONFIG_NAME = '.calibre-separated-storage.json'
DATABASE_CONFIG_NAME = '.calibre-separated-database.json'


def registry():
    # Keep a local record so a disconnected books mount cannot masquerade as
    # a new ordinary library when its marker disappears.
    from calibre.utils.config import JSONConfig
    return JSONConfig('separated-library-storage')


def storage_identity(library_path):
    root = os.path.abspath(library_path)
    known = registry().get(root)
    marker = os.path.join(root, CONFIG_NAME)
    # exists()/lexists() swallow EACCES, ESTALE and similar failures. Probe
    # directly so an inaccessible marker cannot become a new ordinary library.
    try:
        with open(marker, encoding='utf-8') as stream:
            config = json.load(stream)
    except FileNotFoundError:
        if known is not None or os.path.lexists(marker):
            raise
        return None
    if known is not None and config != known:
        raise OSError(f'Separated books storage has changed or is unavailable: {root}')
    return config


def check_database_identity(config):
    if config.get('storage_id'):
        owner_path = os.path.join(config['database_directory'], DATABASE_CONFIG_NAME)
        with open(owner_path, encoding='utf-8') as stream:
            owner = json.load(stream)
        if not isinstance(owner, dict) or owner.get('storage_id') != config['storage_id']:
            raise OSError('The local database folder belongs to different or unavailable storage')


def check_storage(library_path, expected):
    if expected is None:
        return
    if storage_identity(library_path) != expected:
        raise OSError(f'Separated books storage is unavailable: {library_path}')
    check_database_identity(expected)
    directory = expected['database_directory']
    if not os.path.isdir(directory):
        raise FileNotFoundError(f'Local database storage is unavailable: {directory}')
    if expected.get('initialized') and not os.path.isfile(os.path.join(directory, 'metadata.db')):
        raise FileNotFoundError(f'Separated database is unavailable: {directory}')


def mark_initialized(library_path, config):
    # Persist this on the books drive too: losing local application preferences
    # must not allow a missing database to be silently replaced with an empty one.
    if config.get('initialized'):
        return config
    check_storage(library_path, config)
    config = dict(config, initialized=True)
    # Like normal cover and OPF writes, write the destination directly.
    # GVfs SMB can support ordinary writes while rejecting replacement renames.
    # A failed/interrupted write leaves an invalid or mismatched marker, which
    # storage_identity() rejects; never fall back to a new empty database.
    def existing_marker_only(path, flags):
        # Do not recreate a marker on an empty mountpoint if storage vanishes
        # after validation. O_WRONLY remains compatible with GVfs SMB.
        return os.open(path, flags & ~os.O_CREAT)

    with open(os.path.join(library_path, CONFIG_NAME), 'w', encoding='utf-8', opener=existing_marker_only) as stream:
        json.dump(config, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    registry()[os.path.abspath(library_path)] = config
    return config


def library_exists(path):
    if not path:
        return False
    try:
        return os.path.isfile(resolve_database_path(path))
    except (OSError, ValueError):
        return False


def resolve_database_path(library_path: str, *, allow_missing_database: bool = False) -> str:
    """Return the configured metadata.db path, or the standard Calibre path.

    A missing books root is an error for a configured split library: never
    silently initialize a new empty library on an unmounted NAS.
    """
    root = os.path.abspath(library_path)
    default = os.path.join(root, 'metadata.db')
    config = storage_identity(root)
    if config is None:
        if os.path.lexists(os.path.join(root, DATABASE_CONFIG_NAME)):
            raise ValueError('Select the managed books folder, not the separated database folder')
        return default
    if not os.path.isdir(root):
        raise FileNotFoundError(f'Books root is unavailable: {root}')
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
    check_database_identity(config)
    target = os.path.join(database_dir, 'metadata.db')
    if not allow_missing_database and config.get('initialized') and not os.path.isfile(target):
        raise FileNotFoundError(f'Separated database is unavailable: {target}')
    if registry().get(root) is None:
        registry()[root] = config
    return target


def validate_directories(root, database_directory):
    database_directory = os.path.realpath(database_directory)
    books_real = os.path.realpath(root)
    try:
        common = os.path.commonpath((books_real, database_directory))
    except ValueError:  # Different Windows drives are necessarily disjoint.
        common = None
    if common in (books_real, database_directory):
        raise ValueError('Database and books directories must be separate, non-nested folders')


def configure_separated_storage(library_path: str, database_directory: str) -> str:
    """Exclusively configure a *new* normal library before DB initialization.

    Both directories must already exist. Never relocate an existing database.
    Returns the target database path; the caller can then initialize Calibre.
    """
    root = os.path.abspath(library_path)
    database_directory = os.path.abspath(database_directory)
    if not os.path.isdir(root):
        raise FileNotFoundError(f'Books root is unavailable: {root}')
    if not os.path.isdir(database_directory):
        raise FileNotFoundError(f'Database directory is unavailable: {database_directory}')
    validate_directories(root, database_directory)
    if os.path.exists(os.path.join(root, 'metadata.db')):
        raise FileExistsError('Cannot configure an existing standard Calibre library')
    config_path = os.path.join(root, CONFIG_NAME)
    if os.path.lexists(config_path):
        raise FileExistsError(f'Storage configuration already exists: {config_path}')
    target = os.path.join(os.path.realpath(database_directory), 'metadata.db')
    if os.path.exists(target):
        raise FileExistsError(f'Database target already exists: {target}')
    if os.listdir(root) or os.listdir(database_directory):
        raise FileExistsError('New separated libraries require empty books and database folders')
    if not os.access(database_directory, os.W_OK) or not os.access(root, os.W_OK):
        raise PermissionError('Both storage directories must be writable')
    # Use an exclusive create: concurrent attempts cannot overwrite a marker.
    # The marker is written only after all validation has succeeded.
    config = {'version': 1, 'database_directory': os.path.realpath(database_directory), 'storage_id': str(uuid.uuid4())}
    payload = json.dumps(config, indent=2)
    owner_path = os.path.join(database_directory, DATABASE_CONFIG_NAME)
    with open(owner_path, 'x', encoding='utf-8') as stream:
        stream.write(payload + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    try:
        # Exclusive direct creation avoids requiring hard links or replacement
        # renames on GVfs SMB. Never truncate somebody else's marker.
        with open(config_path, 'x', encoding='utf-8') as stream:
            stream.write(payload + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        os.unlink(owner_path)
        raise
    registry()[root] = config
    return target
