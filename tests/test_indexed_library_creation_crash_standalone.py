#!/usr/bin/env python3
"""Linux subprocess crash test for Indexed creation before completion publication."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'linux', 'Linux-only Indexed creator')
class CreationCrashTests(unittest.TestCase):
    def test_sigkill_before_completion_preserves_incomplete_library(self):
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / 'library'
            library.mkdir()
            offline = Path(temp) / 'offline-nas'
            ready = Path(temp) / 'ready'
            script = r"""
import importlib.util
import os
import signal
import sys
import types
from pathlib import Path

root, library, offline, ready = map(Path, sys.argv[1:])
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
def kill_before_completion(path):
    ready.write_text('inspection reached')
    os.kill(os.getpid(), signal.SIGKILL)
creator.inspect_indexed_database = kill_before_completion
creator.create_indexed_library(library, [str(offline)], schema)
"""
            result = subprocess.run(
                [sys.executable, '-c', script, str(ROOT), str(library),
                 str(offline), str(ready)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, -9, result.stderr)
            self.assertTrue(ready.exists())
            self.assertTrue((library / 'indexed-library.json').is_file())
            self.assertTrue((library / 'metadata.db').is_file())
            self.assertFalse((library / 'indexed-library.complete').exists())
            self.assertFalse(offline.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
