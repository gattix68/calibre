#!/usr/bin/env python
# License: GPLv3
"""Resolve an explicitly configured local database path for a managed library.

This is an opt-in, low-level path resolver, not a second library format.
The books root remains Calibre's normal library_path.
"""
import json
import os

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
    return os.path.join(database_dir, 'metadata.db')
