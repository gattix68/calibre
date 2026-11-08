#!/usr/bin/env python
# License: GPLv3
"""Standalone regression tests for separated database path resolution."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from calibre.db.separated_storage import CONFIG_NAME, resolve_database_path


class SeparatedStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'books'
        self.local = Path(self.tmp.name) / 'local-db'
        self.root.mkdir()
        self.local.mkdir()

    def configure(self, database_directory, version=1):
        (self.root / CONFIG_NAME).write_text(
            json.dumps({'version': version, 'database_directory': str(database_directory)}),
            encoding='utf-8',
        )

    def test_unconfigured_library_keeps_standard_database_location(self):
        self.assertEqual(resolve_database_path(str(self.root)), str(self.root / 'metadata.db'))

    def test_separated_library_resolves_local_database(self):
        self.configure(self.local)
        self.assertEqual(resolve_database_path(str(self.root)), str(self.local / 'metadata.db'))

    def test_missing_local_directory_fails_closed(self):
        self.configure(self.local / 'missing')
        with self.assertRaises(FileNotFoundError):
            resolve_database_path(str(self.root))

    def test_relative_database_directory_rejected(self):
        self.configure('relative/path')
        with self.assertRaises(ValueError):
            resolve_database_path(str(self.root))

    def test_same_root_rejected(self):
        self.configure(self.root)
        with self.assertRaises(ValueError):
            resolve_database_path(str(self.root))

    def test_unknown_config_version_rejected(self):
        self.configure(self.local, version=2)
        with self.assertRaises(ValueError):
            resolve_database_path(str(self.root))


if __name__ == '__main__':
    unittest.main()
