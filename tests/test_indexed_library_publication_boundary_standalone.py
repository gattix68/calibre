#!/usr/bin/env python3
"""Linux crash-boundary tests around Indexed completion hard-link publication."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHILD = r"""
import importlib.util
import os
import signal
import sys
import types
from pathlib import Path

root, library, offline, phase = sys.argv[1:]
root, library, offline = map(Path, (root, library, offline))
dbdir = root / 'src/calibre/db'
for name in ('calibre', 'calibre.db'):
    pkg = types.ModuleType(name)
    pkg.__path__ = []
    sys.modules[name] = pkg

def load(name):
    spec = importlib.util.spec_from_file_location('calibre.db.' + name, dbdir / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

for name in ('indexed_library_config', 'indexed_storage_validation',
             'indexed_library_creation', 'indexed_database_init',
             'indexed_database_recovery'):
    load(name)
creator = load('indexed_library_creator')
schema = (root / 'resources/metadata_sqlite.sql').read_text()
real_link = os.link

def crash_at_publication(*args, **kwargs):
    if phase == 'before':
        os.kill(os.getpid(), signal.SIGKILL)
    result = real_link(*args, **kwargs)
    os.kill(os.getpid(), signal.SIGKILL)
    return result

creator.os.link = crash_at_publication if phase != 'cleanup' else real_link
real_unlink = os.unlink

def crash_after_pending_cleanup(path, *args, **kwargs):
    result = real_unlink(path, *args, **kwargs)
    if path == creator.PENDING_COMPLETION_FILENAME:
        os.kill(os.getpid(), signal.SIGKILL)
    return result

if phase == 'cleanup':
    creator.os.unlink = crash_after_pending_cleanup
creator.create_indexed_library(library, [str(offline)], schema)
"""

VERIFY = r"""
import importlib.util
import sys
import types
from pathlib import Path
root, library = map(Path, sys.argv[1:])
dbdir = root / 'src/calibre/db'
for name in ('calibre', 'calibre.db'):
    pkg = types.ModuleType(name)
    pkg.__path__ = []
    sys.modules[name] = pkg
for name in ('indexed_library_config', 'indexed_storage_validation',
             'indexed_database_recovery', 'indexed_library_verification'):
    spec = importlib.util.spec_from_file_location('calibre.db.' + name, dbdir / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
from calibre.db.indexed_library_verification import verify_indexed_library_complete
from calibre.db.indexed_database_recovery import IncompleteIndexedDatabase
try:
    verify_indexed_library_complete(library)
except IncompleteIndexedDatabase:
    sys.exit(0)
sys.exit(1)
"""


@unittest.skipUnless(sys.platform == 'linux', 'Linux-only creation protocol')
class PublicationBoundaryTests(unittest.TestCase):
    def check_phase(self, phase):
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / 'library'
            library.mkdir()
            offline = Path(temp) / 'offline-nas'
            child = subprocess.run(
                [sys.executable, '-c', CHILD, str(ROOT), str(library),
                 str(offline), phase],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(child.returncode, -9, child.stderr)
            self.assertTrue((library / 'indexed-library.json').is_file())
            self.assertTrue((library / 'metadata.db').is_file())
            pending = library / 'indexed-library.complete.pending'
            final = library / 'indexed-library.complete'
            self.assertEqual(pending.exists(), phase != 'cleanup')
            if pending.exists():
                self.assertEqual(pending.read_bytes(), b'indexed-library-complete-v1\n')
            self.assertEqual(final.exists(), phase in ('after', 'cleanup'))
            if phase == 'after':
                self.assertEqual(final.read_bytes(), pending.read_bytes())
            if phase == 'cleanup':
                self.assertEqual(final.read_bytes(), b'indexed-library-complete-v1\n')
            verifier = subprocess.run(
                [sys.executable, '-c', VERIFY, str(ROOT), str(library)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(verifier.returncode, 1 if phase == 'cleanup' else 0, verifier.stderr)
            self.assertFalse(offline.exists())

    def test_crash_immediately_before_atomic_publication(self):
        self.check_phase('before')

    def test_crash_immediately_after_atomic_publication(self):
        self.check_phase('after')

    def test_crash_after_pending_cleanup_before_directory_fsync(self):
        # This is the logical commit point: verification can accept the
        # completed directory, but SIGKILL does not establish power-loss durability.
        self.check_phase('cleanup')


if __name__ == '__main__':
    unittest.main(verbosity=2)
