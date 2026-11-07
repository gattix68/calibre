#!/usr/bin/env python3
"""End-to-end Indexed creation, verification, and interrupted-state isolation."""
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DBDIR = ROOT / 'src/calibre/db'
SCHEMA = (ROOT / 'resources/metadata_sqlite.sql').read_text(encoding='utf-8')
for name in ('calibre', 'calibre.db'):
    package = types.ModuleType(name)
    package.__path__ = []
    sys.modules.setdefault(name, package)


def load(name):
    full_name = 'calibre.db.' + name
    spec = importlib.util.spec_from_file_location(full_name, DBDIR / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


config = load('indexed_library_config')
load('indexed_storage_validation')
load('indexed_library_creation')
load('indexed_database_init')
recovery = load('indexed_database_recovery')
creator = load('indexed_library_creator')
verifier = load('indexed_library_verification')


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.library = root / 'local-library'
        self.library.mkdir()
        self.offline = root / 'offline-nas'
        self.existing = root / 'existing-ebooks'
        self.existing.mkdir()
        self.book = self.existing / 'original.epub'
        self.book.write_bytes(b'original ebook bytes')
        self.before = self.book.read_bytes()
        self.roots = [str(self.offline), str(self.existing)]

    def assert_sources_unchanged(self):
        self.assertFalse(self.offline.exists())
        self.assertEqual(self.book.read_bytes(), self.before)
        self.assertEqual(sorted(p.name for p in self.existing.iterdir()),
                         ['original.epub'])

    def test_create_verify_and_refuse_recreation(self):
        dbpath = creator.create_indexed_library(self.library, self.roots, SCHEMA)
        self.assertEqual(verifier.verify_indexed_library_complete(self.library), dbpath)
        self.assertEqual(config.load_indexed_library_config(self.library)['source_roots'],
                         self.roots)
        with sqlite3.connect('file:' + str(dbpath) + '?mode=ro', uri=True) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 28)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM indexed_files').fetchone()[0], 0)
        before_files = {p.name: p.read_bytes() for p in self.library.iterdir()}
        with self.assertRaises(Exception):
            creator.create_indexed_library(self.library, self.roots, SCHEMA)
        self.assertEqual({p.name: p.read_bytes() for p in self.library.iterdir()},
                         before_files)
        self.assert_sources_unchanged()

    def test_interrupted_inspection_requires_manual_review_and_preserves_files(self):
        with patch.object(creator, 'inspect_indexed_database',
                          side_effect=recovery.IncompleteIndexedDatabase('simulated interruption')):
            with self.assertRaises(recovery.IncompleteIndexedDatabase):
                creator.create_indexed_library(self.library, self.roots, SCHEMA)
        self.assertTrue((self.library / config.CONFIG_FILENAME).is_file())
        self.assertTrue((self.library / 'metadata.db').is_file())
        with self.assertRaises(recovery.IncompleteIndexedDatabase):
            verifier.verify_indexed_library_complete(self.library)
        before_files = {p.name: p.read_bytes() for p in self.library.iterdir()}
        with self.assertRaises(Exception):
            creator.create_indexed_library(self.library, self.roots, SCHEMA)
        self.assertEqual({p.name: p.read_bytes() for p in self.library.iterdir()},
                         before_files)
        self.assert_sources_unchanged()


if __name__ == '__main__':
    unittest.main(verbosity=2)
