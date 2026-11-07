#!/usr/bin/env python3
"""Disposable Indexed Library schema initialization test.

Uses the actual Calibre schema SQL in an in-memory SQLite database. Does not
import Calibre, initialize the application, or access any NAS files.
"""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / 'resources/metadata_sqlite.sql'
CONFIG = ROOT / 'src/calibre/db/indexed_library_config.py'

spec = importlib.util.spec_from_file_location('indexed_library_config', CONFIG)
config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_module)


class IndexedDatabaseInitializationTests(unittest.TestCase):
    def test_disposable_database_schema_and_file_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / 'local-indexed-library'
            library.mkdir()
            marker = library / config_module.CONFIG_FILENAME
            marker.write_text(json.dumps({
                'version': 1, 'mode': 'indexed',
                'source_roots': ['/nonexistent/offline-nas/books'],
            }), encoding='utf-8')

            database_path = config_module.indexed_database_path(library)
            self.assertEqual(database_path, library / 'metadata.db')
            self.assertFalse(database_path.exists())

            # Schema creation is deliberately isolated in memory. Startup must
            # remain fail-closed until Calibre file mutation paths are guarded.
            with self.assertRaisesRegex(RuntimeError, 'not yet available'):
                config_module.check_indexed_library_startup(library)

            db = sqlite3.connect(':memory:')
            try:
                db.create_function('title_sort', 1, lambda title: title)
                db.create_function('uuid4', 0, lambda: 'test-uuid')
                db.executescript(SCHEMA.read_text(encoding='utf-8'))
                self.assertEqual(
                    db.execute('PRAGMA user_version').fetchone()[0], 29
                )
                self.assertIsNotNone(db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='indexed_files'"
                ).fetchone())
                db.execute("INSERT INTO books(id, title) VALUES (1, 'Disposable Test')")
                db.execute(
                    'INSERT INTO indexed_files(book_id, format, file_path, file_size, modified_time_ns) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (1, 'EPUB', '/nonexistent/offline-nas/books/book.epub', 123, 456),
                )
                self.assertEqual(
                    db.execute('SELECT file_path FROM indexed_files WHERE book_id=1').fetchone()[0],
                    '/nonexistent/offline-nas/books/book.epub'
                )
            finally:
                db.close()

            self.assertFalse(database_path.exists())
            self.assertEqual(sorted(p.name for p in library.iterdir()), [marker.name])


if __name__ == '__main__':
    unittest.main(verbosity=2)
