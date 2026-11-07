#!/usr/bin/env python3
"""Standalone tests for read-only inspection of incomplete Indexed databases."""
import importlib.util
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DBDIR = ROOT / 'src/calibre/db'
SCHEMA = (ROOT / 'resources/metadata_sqlite.sql').read_text(encoding='utf-8')


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, DBDIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


for name in ('calibre', 'calibre.db'):
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = []
        sys.modules[name] = pkg

config = load('calibre.db.indexed_library_config', 'indexed_library_config.py')
storage = load('calibre.db.indexed_storage_validation', 'indexed_storage_validation.py')
init = load('calibre.db.indexed_database_init', 'indexed_database_init.py')
recovery = load('calibre.db.indexed_database_recovery', 'indexed_database_recovery.py')


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library = Path(self.temp.name) / 'local'
        self.library.mkdir()
        self.source = Path(self.temp.name) / 'offline-source'
        (self.library / config.CONFIG_FILENAME).write_text(json.dumps({
            'version': 1, 'mode': 'indexed', 'source_roots': [str(self.source)]
        }), encoding='utf-8')

    def test_missing_database_is_rejected_without_writes(self):
        with self.assertRaises(recovery.IncompleteIndexedDatabase):
            recovery.inspect_indexed_database(self.library)
        self.assertEqual(sorted(p.name for p in self.library.iterdir()), [config.CONFIG_FILENAME])
        self.assertFalse(self.source.exists())

    def test_partial_database_is_rejected_and_preserved(self):
        dbpath = self.library / 'metadata.db'
        with sqlite3.connect(dbpath) as db:
            db.execute('CREATE TABLE books (id INTEGER)')
        before = dbpath.read_bytes()
        with self.assertRaises(recovery.IncompleteIndexedDatabase):
            recovery.inspect_indexed_database(self.library)
        self.assertEqual(dbpath.read_bytes(), before)
        self.assertFalse(self.source.exists())

    def test_sidecar_is_rejected_without_cleanup(self):
        dbpath = init.initialize_indexed_database(self.library, SCHEMA)
        sidecar = self.library / 'metadata.db-journal'
        sidecar.write_bytes(b'simulated interrupted journal')
        with self.assertRaisesRegex(recovery.IncompleteIndexedDatabase, 'sidecar'):
            recovery.inspect_indexed_database(self.library)
        self.assertEqual(sidecar.read_bytes(), b'simulated interrupted journal')
        self.assertTrue(dbpath.exists())
        self.assertFalse(self.source.exists())

    def test_dangling_sidecar_symlink_is_rejected_without_changes(self):
        init.initialize_indexed_database(self.library, SCHEMA)
        sidecar = self.library / 'metadata.db-wal'
        sidecar.symlink_to(self.library / 'missing-journal-target')
        self.assertFalse(sidecar.exists())
        self.assertTrue(sidecar.is_symlink())
        with self.assertRaisesRegex(recovery.IncompleteIndexedDatabase, 'sidecar'):
            recovery.inspect_indexed_database(self.library)
        self.assertTrue(sidecar.is_symlink())
        self.assertFalse(self.source.exists())

    def test_completed_database_passes_read_only_inspection(self):
        dbpath = init.initialize_indexed_database(self.library, SCHEMA)
        before = dbpath.read_bytes()
        self.assertEqual(recovery.inspect_indexed_database(self.library), dbpath)
        self.assertEqual(dbpath.read_bytes(), before)
        self.assertFalse(self.source.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
