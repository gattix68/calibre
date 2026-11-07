#!/usr/bin/env python3
"""Standalone regression: destination replacement after preflight must fail closed."""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DBDIR = ROOT / 'src/calibre/db'
SCHEMA = (ROOT / 'resources/metadata_sqlite.sql').read_text(encoding='utf-8')
for name in ('calibre', 'calibre.db'):
    pkg = types.ModuleType(name)
    pkg.__path__ = []
    sys.modules[name] = pkg


def load(name):
    spec = importlib.util.spec_from_file_location('calibre.db.' + name, DBDIR / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


for name in ('indexed_library_config', 'indexed_storage_validation',
             'indexed_library_creation', 'indexed_database_init',
             'indexed_database_recovery'):
    load(name)
creator = load('indexed_library_creator')


class CreatorRaceTests(unittest.TestCase):
    def test_replaced_destination_after_preflight_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            destination = base / 'library'
            destination.mkdir()
            offline = base / 'offline-nas'
            original = creator.validate_indexed_creation

            def replace_after_preflight(*args):
                plan = original(*args)
                destination.rename(base / 'original-library')
                destination.mkdir()
                return plan

            with patch.object(creator, 'validate_indexed_creation',
                              side_effect=replace_after_preflight):
                with self.assertRaises(RuntimeError):
                    creator.create_indexed_library(destination, [str(offline)], SCHEMA)
            self.assertEqual(list(destination.iterdir()), [])
            self.assertEqual(list((base / 'original-library').iterdir()), [])
            self.assertFalse(offline.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
