#!/usr/bin/env python3
"""Linux SIGKILL during completion-marker publication; never touch NAS roots."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'linux', 'Linux-only Indexed creator')
class CompletionCrashTests(unittest.TestCase):
    def test_sigkill_during_completion_write_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / 'library'
            library.mkdir()
            offline = Path(temp) / 'offline-nas'
            script = r"""
import importlib.util
import os
import signal
import sys
import types
from pathlib import Path

root, library, offline = map(Path, sys.argv[1:])
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
real_fdopen = creator.os.fdopen

class KillOnCompletionWrite:
    def __init__(self, handle):
        self.handle = handle
    def __enter__(self):
        self.handle.__enter__()
        return self
    def __exit__(self, *args):
        return self.handle.__exit__(*args)
    def write(self, data):
        self.handle.write(data[:8])
        self.handle.flush()
        os.fsync(self.handle.fileno())
        os.kill(os.getpid(), signal.SIGKILL)
    def __getattr__(self, key):
        return getattr(self.handle, key)

def intercepted_fdopen(fd, mode):
    handle = real_fdopen(fd, mode)
    try:
        target = os.readlink('/proc/self/fd/' + str(fd))
    except OSError:
        target = ''
    if target.endswith('/indexed-library.complete.pending'):
        return KillOnCompletionWrite(handle)
    return handle

creator.os.fdopen = intercepted_fdopen
creator.create_indexed_library(library, [str(offline)], schema)
"""
            result = subprocess.run(
                [sys.executable, '-c', script, str(ROOT), str(library), str(offline)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, -9, result.stderr)
            completion = library / 'indexed-library.complete.pending'
            self.assertTrue(completion.is_file())
            self.assertFalse((library / 'indexed-library.complete').exists())
            self.assertEqual(completion.read_bytes(), b'indexed-')
            self.assertTrue((library / 'indexed-library.json').is_file())
            self.assertTrue((library / 'metadata.db').is_file())
            self.assertFalse(offline.exists())
            # Validate independently in a clean process to avoid import monkeypatches.
            verify = r"""
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
            checked = subprocess.run(
                [sys.executable, '-c', verify, str(ROOT), str(library)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(completion.read_bytes(), b'indexed-')
            self.assertFalse(offline.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
