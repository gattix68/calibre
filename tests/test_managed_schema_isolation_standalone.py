#!/usr/bin/env python3
"""Regression: Managed schema never acquires Indexed-only tables."""
import importlib.util
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / 'resources/metadata_sqlite.sql'
UPGRADES = ROOT / 'src/calibre/db/schema_upgrades.py'
CONFIG = ROOT / 'src/calibre/db/indexed_library_config.py'
spec = importlib.util.spec_from_file_location('indexed_library_config', CONFIG)
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


class ManagedSchemaIsolationTests(unittest.TestCase):
    def test_managed_schema_has_no_indexed_tables(self):
        with sqlite3.connect(':memory:') as db:
            db.executescript(SCHEMA.read_text(encoding='utf-8'))
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 28)
            self.assertIsNone(db.execute(
                "SELECT name FROM sqlite_master WHERE name='indexed_files'"
            ).fetchone())
            db.executescript(config.INDEXED_FILES_SCHEMA)
            self.assertIsNotNone(db.execute(
                "SELECT name FROM sqlite_master WHERE name='indexed_files'"
            ).fetchone())

    def test_managed_migrations_do_not_install_indexed_extension(self):
        source = UPGRADES.read_text(encoding='utf-8')
        self.assertNotIn('def upgrade_version_28(', source)
        self.assertNotIn('INDEXED_FILES_SCHEMA', source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
