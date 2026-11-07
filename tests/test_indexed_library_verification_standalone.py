#!/usr/bin/env python3
"""Standalone read-only completion verification regression tests."""
import importlib.util
import fcntl
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DBDIR = ROOT / 'src/calibre/db'
SCHEMA = (ROOT / 'resources/metadata_sqlite.sql').read_text(encoding='utf-8')
for name in ('calibre', 'calibre.db'):
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = []
        sys.modules[name] = pkg


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, DBDIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


for name in ('indexed_library_config', 'indexed_storage_validation',
             'indexed_library_creation', 'indexed_database_init',
             'indexed_database_recovery', 'indexed_library_creator'):
    load('calibre.db.' + name, name + '.py')
verification = load('calibre.db.indexed_library_verification', 'indexed_library_verification.py')
creator = sys.modules['calibre.db.indexed_library_creator']
Incomplete = sys.modules['calibre.db.indexed_database_recovery'].IncompleteIndexedDatabase


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library = Path(self.temp.name) / 'library'
        self.library.mkdir()
        self.offline = Path(self.temp.name) / 'offline-nas'
        creator.create_indexed_library(self.library, [str(self.offline)], SCHEMA)

    def assert_rejected(self):
        with self.assertRaises(Incomplete):
            verification.verify_indexed_library_complete(self.library)
        self.assertFalse(self.offline.exists())

    def test_complete_library_passes_without_nas(self):
        self.assertEqual(verification.verify_indexed_library_complete(self.library),
                         self.library / 'metadata.db')
        self.assertFalse(self.offline.exists())

    def test_active_creator_lock_rejects_even_valid_completion(self):
        fd = os.open(self.library, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assert_rejected()
            self.assertEqual(
                (self.library / verification.COMPLETION_FILENAME).read_bytes(),
                verification.COMPLETION_SIGNATURE,
            )
        finally:
            os.close(fd)
        self.assertEqual(verification.verify_indexed_library_complete(self.library),
                         self.library / 'metadata.db')

    def test_missing_completion_rejected(self):
        (self.library / verification.COMPLETION_FILENAME).unlink()
        self.assert_rejected()

    def test_corrupt_completion_rejected(self):
        (self.library / verification.COMPLETION_FILENAME).write_bytes(b'bad')
        self.assert_rejected()

    def test_trailing_completion_bytes_rejected(self):
        (self.library / verification.COMPLETION_FILENAME).write_bytes(
            verification.COMPLETION_SIGNATURE + b'extra')
        self.assert_rejected()

    def test_symlink_completion_rejected(self):
        marker = self.library / verification.COMPLETION_FILENAME
        marker.unlink()
        marker.symlink_to(self.library / 'metadata.db')
        self.assert_rejected()

    def test_sqlite_sidecar_rejected_without_changes(self):
        sidecar = self.library / 'metadata.db-journal'
        sidecar.write_bytes(b'interrupted')
        self.assert_rejected()
        self.assertEqual(sidecar.read_bytes(), b'interrupted')

    def test_extra_file_rejected_without_changes(self):
        extra = self.library / 'unrelated.txt'
        extra.write_text('preserve')
        self.assert_rejected()
        self.assertEqual(extra.read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main(verbosity=2)
