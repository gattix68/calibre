#!/usr/bin/env python3
"""Standalone tests for explicit Indexed database creation; no Calibre import."""
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
