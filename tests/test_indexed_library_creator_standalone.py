#!/usr/bin/env python3
"""Isolated controlled creation tests; no Calibre runtime or NAS access."""
import importlib.util
import fcntl
import os
import json
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
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = []
        sys.modules[name] = package


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, DBDIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


config = load('calibre.db.indexed_library_config', 'indexed_library_config.py')
storage = load('calibre.db.indexed_storage_validation', 'indexed_storage_validation.py')
preflight = load('calibre.db.indexed_library_creation', 'indexed_library_creation.py')
init = load('calibre.db.indexed_database_init', 'indexed_database_init.py')
recovery = load('calibre.db.indexed_database_recovery', 'indexed_database_recovery.py')
creator = load('calibre.db.indexed_library_creator', 'indexed_library_creator.py')


class CreatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library = Path(self.temp.name) / 'local'
        self.library.mkdir()
        self.offline = Path(self.temp.name) / 'offline-nas'

    def test_concurrent_creator_directory_lock_fails_closed(self):
        fd = os.open(self.library, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                creator.create_indexed_library(self.library, [str(self.offline)], SCHEMA)
            self.assertEqual(list(self.library.iterdir()), [])
            self.assertFalse(self.offline.exists())
        finally:
            os.close(fd)
        creator.create_indexed_library(self.library, [str(self.offline)], SCHEMA)
        self.assertTrue((self.library / creator.COMPLETION_FILENAME).exists())

    def test_create_without_touching_offline_source(self):
        dbpath = creator.create_indexed_library(self.library, [str(self.offline)], SCHEMA)
        self.assertEqual(dbpath, self.library / 'metadata.db')
        self.assertEqual(config.load_indexed_library_config(self.library)['source_roots'],
                         [str(self.offline)])
        with sqlite3.connect(dbpath) as db:
            self.assertIsNotNone(db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='indexed_files'").fetchone())
        self.assertEqual((self.library / creator.COMPLETION_FILENAME).read_bytes(),
                         b'indexed-library-complete-v1\n')
        self.assertFalse(self.offline.exists())

    def test_failed_schema_rolls_back_marker_and_database(self):
        with self.assertRaises(sqlite3.Error):
            creator.create_indexed_library(self.library, [str(self.offline)], 'INVALID SQL;')
        self.assertEqual(list(self.library.iterdir()), [])
        self.assertFalse(self.offline.exists())

    def test_existing_user_file_is_preserved(self):
        sentinel = self.library / 'keep.txt'
        sentinel.write_text('untouched')
        with self.assertRaises(preflight.InvalidIndexedCreation):
            creator.create_indexed_library(self.library, [str(self.offline)], SCHEMA)
        self.assertEqual(sentinel.read_text(), 'untouched')
        self.assertFalse(self.offline.exists())

    def test_marker_is_not_overwritten_if_created_after_preflight(self):
        original = creator.validate_indexed_creation
        marker = self.library / config.CONFIG_FILENAME

        def racing_preflight(*args):
            result = original(*args)
            marker.write_text('other-process')
            return result

        with patch.object(creator, 'validate_indexed_creation', side_effect=racing_preflight):
            with self.assertRaises(FileExistsError):
                creator.create_indexed_library(self.library, [str(self.offline)], SCHEMA)
        self.assertEqual(marker.read_text(), 'other-process')
        self.assertFalse((self.library / 'metadata.db').exists())


    def test_failed_initializer_with_orphan_sidecar_keeps_indexed_marker(self):
        sidecar = self.library / 'metadata.db-journal'

        def interrupted_initializer(*args):
            sidecar.write_bytes(b'preserve-interrupted-journal')
            raise RuntimeError('simulated interrupted SQLite initialization')

        with patch.object(creator, 'initialize_indexed_database',
                          side_effect=interrupted_initializer):
            with self.assertRaises(RuntimeError):
                creator.create_indexed_library(self.library, [str(self.offline)], SCHEMA)
        self.assertTrue((self.library / config.CONFIG_FILENAME).is_file())
        self.assertEqual(sidecar.read_bytes(), b'preserve-interrupted-journal')
        self.assertFalse((self.library / creator.COMPLETION_FILENAME).exists())
        self.assertFalse(self.offline.exists())

    def test_mutation_during_completion_publication_retracts_marker(self):
        original = creator._check_final_inputs
        calls = 0

        def mutate_on_final_check(*args):
            nonlocal calls
            calls += 1
            if calls == 3:
                db = self.library / 'metadata.db'
                replacement = self.library / 'other-database'
                replacement.write_bytes(db.read_bytes())
                replacement.replace(db)
            return original(*args)

        with patch.object(creator, '_check_final_inputs', side_effect=mutate_on_final_check):
            with self.assertRaisesRegex(RuntimeError, 'database changed'):
                creator.create_indexed_library(self.library, [str(self.offline)], SCHEMA)
        self.assertEqual(calls, 3)
        self.assertFalse((self.library / creator.COMPLETION_FILENAME).exists())
        self.assertTrue((self.library / config.CONFIG_FILENAME).exists())
        self.assertTrue((self.library / 'metadata.db').exists())
        self.assertFalse(self.offline.exists())

    def test_database_replacement_during_inspection_rejected(self):
        original = creator.inspect_indexed_database

        def replace_database(library):
            result = original(library)
            db = self.library / 'metadata.db'
            replacement = self.library / 'replacement'
            replacement.write_bytes(db.read_bytes())
            replacement.replace(db)
            return result

        with patch.object(creator, 'inspect_indexed_database', side_effect=replace_database):
            with self.assertRaisesRegex(RuntimeError, 'database changed'):
                creator.create_indexed_library(self.library, [str(self.offline)], SCHEMA)
        self.assertFalse((self.library / creator.COMPLETION_FILENAME).exists())
        self.assertTrue((self.library / config.CONFIG_FILENAME).exists())
        self.assertFalse(self.offline.exists())

    def test_configuration_mutation_during_inspection_rejected(self):
        original = creator.inspect_indexed_database

        def modify_config(library):
            result = original(library)
            marker = self.library / config.CONFIG_FILENAME
            marker.write_bytes(marker.read_bytes() + b' ')
            return result

        with patch.object(creator, 'inspect_indexed_database', side_effect=modify_config):
            with self.assertRaisesRegex(RuntimeError, 'configuration changed'):
                creator.create_indexed_library(self.library, [str(self.offline)], SCHEMA)
        self.assertFalse((self.library / creator.COMPLETION_FILENAME).exists())
        self.assertTrue((self.library / 'metadata.db').exists())
        self.assertFalse(self.offline.exists())

    def test_failed_final_inspection_preserves_incomplete_library(self):
        with patch.object(creator, 'inspect_indexed_database',
                          side_effect=recovery.IncompleteIndexedDatabase('simulated')):
            with self.assertRaises(recovery.IncompleteIndexedDatabase):
                creator.create_indexed_library(self.library, [str(self.offline)], SCHEMA)
        self.assertTrue((self.library / config.CONFIG_FILENAME).exists())
        self.assertTrue((self.library / 'metadata.db').exists())
        self.assertFalse((self.library / creator.COMPLETION_FILENAME).exists())
        self.assertFalse(self.offline.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
