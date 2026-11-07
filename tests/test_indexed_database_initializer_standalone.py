#!/usr/bin/env python3
"""Standalone tests for explicit Indexed database creation; no Calibre import."""
import importlib.util
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DBDIR = ROOT / 'src/calibre/db'
SCHEMA = (ROOT / 'resources/metadata_sqlite.sql').read_text(encoding='utf-8')


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Supply only the package namespaces; do not import Calibre's runtime.
for name in ('calibre', 'calibre.db'):
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = []
        sys.modules[name] = package
config = load_module('calibre.db.indexed_library_config', DBDIR / 'indexed_library_config.py')
storage = load_module('calibre.db.indexed_storage_validation', DBDIR / 'indexed_storage_validation.py')
initializer = load_module('calibre.db.indexed_database_init', DBDIR / 'indexed_database_init.py')


class IndexedDatabaseInitializerTests(unittest.TestCase):
    def make_library(self, temp):
        library = Path(temp) / 'local'
        library.mkdir()
        offline = Path(temp) / 'unmounted-nas'
        (library / config.CONFIG_FILENAME).write_text(json.dumps({
            'version': 1, 'mode': 'indexed', 'source_roots': [str(offline)]
        }), encoding='utf-8')
        return library, offline

    def test_create_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            library, offline = self.make_library(temp)
            dbpath = initializer.initialize_indexed_database(library, SCHEMA)
            self.assertEqual(dbpath, library / 'metadata.db')
            with sqlite3.connect(f'file:{dbpath}?mode=ro', uri=True) as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 28)
                self.assertIsNotNone(db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='indexed_files'"
                ).fetchone())
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            before = dbpath.read_bytes()
            with self.assertRaises(FileExistsError):
                initializer.initialize_indexed_database(library, SCHEMA)
            self.assertEqual(dbpath.read_bytes(), before)
            self.assertFalse(offline.exists())

    def test_reject_managed_and_cleanup_failed_initialization(self):
        with tempfile.TemporaryDirectory() as temp:
            library, offline = self.make_library(temp)
            dbpath = library / 'metadata.db'
            with self.assertRaises(sqlite3.Error):
                initializer.initialize_indexed_database(library, 'NOT VALID SQL;')
            self.assertFalse(dbpath.exists())
            self.assertFalse(offline.exists())
            (library / config.CONFIG_FILENAME).unlink()
            with self.assertRaises(config.InvalidIndexedLibraryConfig):
                initializer.initialize_indexed_database(library, SCHEMA)
            self.assertFalse(dbpath.exists())


    def test_existing_files_and_invalid_config_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            library, offline = self.make_library(temp)
            sentinel = library / 'existing-user-file.txt'
            sentinel.write_text('must remain unchanged', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                initializer.initialize_indexed_database(library, SCHEMA)
            self.assertEqual(sentinel.read_text(encoding='utf-8'), 'must remain unchanged')
            self.assertFalse((library / 'metadata.db').exists())
            sentinel.unlink()

            marker = library / config.CONFIG_FILENAME
            marker.write_text('not-json', encoding='utf-8')
            with self.assertRaises(config.InvalidIndexedLibraryConfig):
                initializer.initialize_indexed_database(library, SCHEMA)
            self.assertFalse((library / 'metadata.db').exists())
            self.assertFalse(offline.exists())

    def test_missing_directory_and_symlink_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / 'missing'
            with self.assertRaises(FileNotFoundError):
                initializer.initialize_indexed_database(missing, SCHEMA)
            library, offline = self.make_library(temp)
            marker = library / config.CONFIG_FILENAME
            target = Path(temp) / 'external-config.json'
            target.write_text(marker.read_text(encoding='utf-8'), encoding='utf-8')
            marker.unlink()
            marker.symlink_to(target)
            with self.assertRaises(ValueError):
                initializer.initialize_indexed_database(library, SCHEMA)
            self.assertFalse((library / 'metadata.db').exists())
            self.assertFalse(offline.exists())


    def test_reject_source_overlap_and_symlinked_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            library, offline = self.make_library(temp)
            marker = library / config.CONFIG_FILENAME
            for root in (str(library), str(library / 'ebooks'), str(Path(temp))):
                marker.write_text(json.dumps({
                    'version': 1, 'mode': 'indexed', 'source_roots': [root]
                }), encoding='utf-8')
                with self.assertRaises(config.InvalidIndexedLibraryConfig):
                    initializer.initialize_indexed_database(library, SCHEMA)
                self.assertFalse((library / 'metadata.db').exists())
            marker.write_text(json.dumps({
                'version': 1, 'mode': 'indexed', 'source_roots': [str(offline)]
            }), encoding='utf-8')
            alias = Path(temp) / 'alias'
            alias.symlink_to(library, target_is_directory=True)
            with self.assertRaises(config.InvalidIndexedLibraryConfig):
                initializer.initialize_indexed_database(alias, SCHEMA)
            self.assertFalse((library / 'metadata.db').exists())


    def test_network_or_unknown_storage_cannot_create_database(self):
        with tempfile.TemporaryDirectory() as temp:
            library, offline = self.make_library(temp)
            dbpath = library / 'metadata.db'
            for reason in ('cifs network mount', 'unknown filesystem'):
                with self.subTest(reason=reason):
                    with patch.object(initializer, 'require_local_indexed_storage',
                                      side_effect=storage.UnverifiedIndexedStorage(reason)):
                        with self.assertRaises(storage.UnverifiedIndexedStorage):
                            initializer.initialize_indexed_database(library, SCHEMA)
                    self.assertFalse(dbpath.exists())
            self.assertFalse(offline.exists())


    def test_directory_identity_change_refuses_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            library, offline = self.make_library(temp)
            original = initializer.verify_indexed_destination_identity

            def changed_identity(path, identity):
                raise RuntimeError('Indexed database directory changed during initialization')

            with patch.object(initializer, 'verify_indexed_destination_identity',
                              side_effect=changed_identity):
                with self.assertRaisesRegex(RuntimeError, 'directory changed'):
                    initializer.initialize_indexed_database(library, SCHEMA)
            self.assertFalse((library / 'metadata.db').exists())
            self.assertFalse(offline.exists())

    def test_storage_change_after_exclusive_create_cleans_up(self):
        with tempfile.TemporaryDirectory() as temp:
            library, offline = self.make_library(temp)
            original = initializer.verify_indexed_destination_identity
            checks = [0]

            def fail_second_check(path, identity):
                checks[0] += 1
                if checks[0] == 2:
                    raise storage.UnverifiedIndexedStorage('mount changed')
                return original(path, identity)

            with patch.object(initializer, 'verify_indexed_destination_identity',
                              side_effect=fail_second_check):
                with self.assertRaisesRegex(storage.UnverifiedIndexedStorage, 'mount changed'):
                    initializer.initialize_indexed_database(library, SCHEMA)
            self.assertEqual(checks[0], 2)
            self.assertFalse((library / 'metadata.db').exists())
            self.assertFalse(offline.exists())


    def test_cleanup_uses_original_directory_after_rename(self):
        with tempfile.TemporaryDirectory() as temp:
            library, offline = self.make_library(temp)
            renamed = Path(temp) / 'renamed-local'
            replacement = library
            original_connect = initializer.sqlite3.connect

            def rename_and_fail(*args, **kwargs):
                library.rename(renamed)
                replacement.mkdir()
                (replacement / 'metadata.db').write_bytes(b'unrelated-file')
                raise sqlite3.OperationalError('simulated database open failure')

            with patch.object(initializer.sqlite3, 'connect', side_effect=rename_and_fail):
                with self.assertRaisesRegex(sqlite3.OperationalError, 'simulated'):
                    initializer.initialize_indexed_database(library, SCHEMA)
            self.assertFalse((renamed / 'metadata.db').exists())
            self.assertEqual((replacement / 'metadata.db').read_bytes(), b'unrelated-file')
            self.assertFalse(offline.exists())


    def test_sqlite_uses_held_directory_after_path_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            library, offline = self.make_library(temp)
            renamed = Path(temp) / 'renamed-local'
            original_connect = initializer.sqlite3.connect
            observed = []

            def rename_then_connect(path, *args, **kwargs):
                observed.append(str(path))
                library.rename(renamed)
                library.mkdir()
                (library / 'metadata.db').write_bytes(b'unrelated-file')
                return original_connect(path, *args, **kwargs)

            with patch.object(initializer.sqlite3, 'connect', side_effect=rename_then_connect):
                result = initializer.initialize_indexed_database(library, SCHEMA)
            self.assertTrue(observed[0].startswith('/proc/self/fd/'))
            self.assertEqual(result, library / 'metadata.db')
            self.assertEqual((library / 'metadata.db').read_bytes(), b'unrelated-file')
            with original_connect(renamed / 'metadata.db') as db:
                self.assertIsNotNone(db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='indexed_files'"
                ).fetchone())
            self.assertFalse(offline.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
