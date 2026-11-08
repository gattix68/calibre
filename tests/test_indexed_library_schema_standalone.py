#!/usr/bin/env python3
"""Standalone tests for the Indexed-only SQLite schema."""
import importlib.util
from pathlib import Path
import sqlite3
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'src/calibre/db/indexed_library_config.py'
spec = importlib.util.spec_from_file_location('indexed_library_config', FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class IndexedSchemaTests(unittest.TestCase):
    def make_db(self):
        db = sqlite3.connect(':memory:')
        db.execute('CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT)')
        for statement in mod.INDEXED_FILES_SCHEMA:
            db.execute(statement)
        return db

    def test_schema_is_a_sequence_of_complete_statements(self):
        self.assertIsInstance(mod.INDEXED_FILES_SCHEMA, tuple)
        self.assertEqual(len(mod.INDEXED_FILES_SCHEMA), 2)
        self.assertTrue(all(statement.strip() for statement in mod.INDEXED_FILES_SCHEMA))

    def test_registers_multiple_formats_for_one_book(self):
        db = self.make_db()
        db.execute("INSERT INTO books(id, title) VALUES (1, 'Book')")
        db.executemany(
            'INSERT INTO indexed_files(book_id, format, file_path, file_size, modified_time_ns) VALUES (?, ?, ?, ?, ?)',
            [(1, 'EPUB', '/library/Book.epub', 100, 10),
             (1, 'PDF', '/library/Book.pdf', 200, 20)],
        )
        rows = db.execute(
            'SELECT format, file_path FROM indexed_files WHERE book_id=1 ORDER BY format'
        ).fetchall()
        self.assertEqual(rows, [('EPUB', '/library/Book.epub'), ('PDF', '/library/Book.pdf')])

    def test_book_delete_cascades_mapping_only(self):
        db = self.make_db()
        db.execute("INSERT INTO books(id, title) VALUES (1, 'Book')")
        db.execute(
            'INSERT INTO indexed_files VALUES (1, ?, ?, ?, ?)',
            ('CBZ', '/nas/comics/Book.cbz', 300, 30),
        )
        db.execute('DELETE FROM books WHERE id=1')
        self.assertEqual(db.execute('SELECT * FROM indexed_files').fetchall(), [])
        # The trigger removes only the mapping row. The source is not a DB-managed file.
        self.assertEqual(db.execute('SELECT COUNT(*) FROM books').fetchone()[0], 0)

    def test_duplicate_format_is_rejected_by_primary_key(self):
        db = self.make_db()
        db.execute("INSERT INTO books(id, title) VALUES (1, 'Book')")
        row = (1, 'EPUB', '/nas/Book.epub', 100, 10)
        db.execute('INSERT INTO indexed_files VALUES (?, ?, ?, ?, ?)', row)
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute('INSERT INTO indexed_files VALUES (?, ?, ?, ?, ?)',
                       (1, 'epub', '/nas/Book-copy.epub', 101, 11))


if __name__ == '__main__':
    unittest.main(verbosity=2)
