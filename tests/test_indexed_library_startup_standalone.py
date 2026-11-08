#!/usr/bin/env python3
"""Isolated Indexed Library startup tests; no Calibre imports or NAS access."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'src/calibre/db/indexed_library_config.py'

spec = importlib.util.spec_from_file_location('indexed_library_config', CONFIG)
config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_module)



class IndexedLibraryStartupTests(unittest.TestCase):
    def test_local_database_path_resolution(self):
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / 'local-library'
            library.mkdir()
            with self.assertRaises(config_module.InvalidIndexedLibraryConfig):
                config_module.indexed_database_path(library)

            marker = library / config_module.CONFIG_FILENAME
            marker.write_text(json.dumps({
                'version': 1, 'mode': 'indexed',
                'source_roots': ['/nonexistent/offline-nas/books'],
            }), encoding='utf-8')
            expected = library / 'metadata.db'
            self.assertEqual(config_module.indexed_database_path(library), expected)
            self.assertFalse(expected.exists())

            marker.write_text('{"version":1,"mode":"managed","source_roots":[]}', encoding='utf-8')
            with self.assertRaises(config_module.InvalidIndexedLibraryConfig):
                config_module.indexed_database_path(library)
            self.assertFalse(expected.exists())

    def test_modes_and_offline_root(self):
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp)
            marker = library / config_module.CONFIG_FILENAME
            self.assertIsNone(config_module.load_indexed_library_config(library))
            config_module.check_indexed_library_startup(library)

            cfg = {'version': 1, 'mode': 'indexed',
                   'source_roots': ['/nonexistent/offline-nas/books']}
            marker.write_text(json.dumps(cfg), encoding='utf-8')
            loaded = config_module.load_indexed_library_config(library)
            self.assertEqual(loaded, cfg)
            with self.assertRaisesRegex(RuntimeError, 'database is missing or invalid'):
                config_module.check_indexed_library_startup(library)

            dbpath = library / 'metadata.db'
            with sqlite3.connect(dbpath) as db:
                db.executescript('''
                    CREATE TABLE books (id INTEGER PRIMARY KEY);
                    CREATE TABLE data (id INTEGER PRIMARY KEY, book INTEGER, format TEXT);
                    CREATE TABLE indexed_files (
                        book_id INTEGER, format TEXT, file_path TEXT,
                        file_size INTEGER, modified_time_ns INTEGER
                    );
                ''')
            (library / 'indexed-library.complete').write_bytes(
                b'indexed-library-complete-v1\n'
            )
            config_module.check_indexed_library_startup(library)

            marker.write_text('{"mode":"invalid"}', encoding='utf-8')
            with self.assertRaises(config_module.InvalidIndexedLibraryConfig):
                config_module.load_indexed_library_config(library)
            self.assertTrue((library / 'metadata.db').is_file())

    def test_dangling_symlink_marker_blocks_managed_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp)
            marker = library / config_module.CONFIG_FILENAME
            marker.symlink_to(library / 'missing-target')
            with self.assertRaises(config_module.InvalidIndexedLibraryConfig):
                config_module.check_indexed_library_startup(library)

    def test_directory_marker_blocks_managed_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp)
            (library / config_module.CONFIG_FILENAME).mkdir()
            with self.assertRaises(config_module.InvalidIndexedLibraryConfig):
                config_module.check_indexed_library_startup(library)

    def test_partial_marker_blocks_managed_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp)
            (library / config_module.CONFIG_FILENAME).write_bytes(b'{"version":')
            with self.assertRaises(config_module.InvalidIndexedLibraryConfig):
                config_module.check_indexed_library_startup(library)


if __name__ == '__main__':
    unittest.main(verbosity=2)
