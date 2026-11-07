#!/usr/bin/env python3
"""Linux-only crash simulation for Indexed DB inspection.

Runs exclusively in a temporary local directory; never accesses source roots.
"""
import importlib.util
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest

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
        package = types.ModuleType(name)
        package.__path__ = []
        sys.modules[name] = package

config = load('calibre.db.indexed_library_config', 'indexed_library_config.py')
storage = load('calibre.db.indexed_storage_validation', 'indexed_storage_validation.py')
init = load('calibre.db.indexed_database_init', 'indexed_database_init.py')
recovery = load('calibre.db.indexed_database_recovery', 'indexed_database_recovery.py')

CHILD = r"""
import sqlite3
import sys
dbpath = sys.argv[1]
db = sqlite3.connect(dbpath, isolation_level=None)
db.execute('PRAGMA journal_mode=DELETE')
db.execute('PRAGMA synchronous=FULL')
db.execute('BEGIN IMMEDIATE')
db.execute('CREATE TABLE crash_test (value BLOB)')
db.execute('INSERT INTO crash_test VALUES (zeroblob(1048576))')
# Signal only after the rollback journal is on disk and transaction is active.
print('READY', flush=True)
sys.stdin.buffer.read(1)
"""


@unittest.skipUnless(sys.platform == 'linux', 'Linux crash simulation only')
class CrashRecoveryTests(unittest.TestCase):
    def test_killed_writer_is_not_accepted_or_modified(self):
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / 'local'
            library.mkdir()
            offline = Path(temp) / 'offline-nas'
            (library / config.CONFIG_FILENAME).write_text(json.dumps({
                'version': 1, 'mode': 'indexed', 'source_roots': [str(offline)]
            }), encoding='utf-8')
            dbpath = init.initialize_indexed_database(library, SCHEMA)
            child = subprocess.Popen(
                [sys.executable, '-c', CHILD, str(dbpath)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(child.stdout.readline().strip(), 'READY')
                child.kill()
                child.wait(timeout=10)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=10)
                child.stdin.close()
                child.stdout.close()
                child.stderr.close()
            journal = library / 'metadata.db-journal'
            self.assertTrue(journal.exists(), 'Expected hot rollback journal after SIGKILL')
            before_db = dbpath.read_bytes()
            before_journal = journal.read_bytes()
            with self.assertRaisesRegex(recovery.IncompleteIndexedDatabase, 'sidecar'):
                recovery.inspect_indexed_database(library)
            self.assertEqual(dbpath.read_bytes(), before_db)
            self.assertEqual(journal.read_bytes(), before_journal)
            self.assertFalse(offline.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
