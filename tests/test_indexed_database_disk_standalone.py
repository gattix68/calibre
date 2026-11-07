#!/usr/bin/env python3
"""Verify a real, disposable local Indexed metadata.db without NAS access."""
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
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


class IndexedDatabaseDiskTests(unittest.TestCase):
    def test_local_database_persists_and_source_is_untouched(self):
        with tempfile.TemporaryDirectory(prefix='calibre-indexed-test-') as temp:
            library = Path(temp) / 'indexed-library'
            library.mkdir()
            source_root = Path(temp) / 'offline-source'
            self.assertFalse(source_root.exists())
            marker = library / config.CONFIG_FILENAME
            marker.write_text(json.dumps({
                'version': 1, 'mode': 'indexed',
                'source_roots': [str(source_root)],
            }), encoding='utf-8')
            dbpath = config.indexed_database_path(library)
            self.assertEqual(dbpath.parent, library)
            self.assertFalse(dbpath.exists())
            with self.assertRaisesRegex(RuntimeError, 'not yet available'):
                config.check_indexed_library_startup(library)

            with sqlite3.connect(dbpath) as db:
                # Calibre's schema triggers call this application-defined function.
                db.create_function('title_sort', 1, lambda title: title)
                db.create_function('uuid4', 0, lambda: 'disposable-test-uuid')
                db.executescript(SCHEMA.read_text(encoding='utf-8'))
                db.execute('PRAGMA foreign_keys=ON')
                db.execute("INSERT INTO books(id, title) VALUES (1, 'Test Book')")
                db.execute(
                    'INSERT INTO indexed_files(book_id, format, file_path, file_size, modified_time_ns) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (1, 'EPUB', str(source_root / 'test.epub'), 100, 200),
                )
                db.commit()

            self.assertTrue(dbpath.is_file())
            with sqlite3.connect(f'file:{dbpath}?mode=ro', uri=True) as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 29)
                self.assertEqual(
                    db.execute('SELECT title FROM books WHERE id=1').fetchone()[0],
                    'Test Book',
                )
                self.assertEqual(
                    db.execute('SELECT file_path FROM indexed_files WHERE book_id=1').fetchone()[0],
                    str(source_root / 'test.epub'),
                )
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertFalse(source_root.exists())
            self.assertEqual({p.name for p in library.iterdir()}, {
                config.CONFIG_FILENAME, 'metadata.db',
            })


if __name__ == '__main__':
    unittest.main(verbosity=2)
