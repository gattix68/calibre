#!/usr/bin/env python3
"""Read-only Indexed creation preflight tests without importing Calibre."""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

DBDIR = Path(__file__).resolve().parents[1] / 'src/calibre/db'
for name in ('calibre', 'calibre.db'):
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = []
        sys.modules[name] = package


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, DBDIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


storage = load('calibre.db.indexed_storage_validation', 'indexed_storage_validation.py')
creation = load('calibre.db.indexed_library_creation', 'indexed_library_creation.py')


class IndexedCreationTests(unittest.TestCase):
    def test_offline_source_accepted_without_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'local'
            dest.mkdir()
            offline = Path(temp) / 'offline-nas'
            result = creation.validate_indexed_creation(dest, [str(offline), str(offline)])
            self.assertEqual(result['source_roots'], [str(offline)])
            self.assertEqual(result['library_directory'], str(dest))
            self.assertEqual(list(dest.iterdir()), [])
            self.assertFalse(offline.exists())

    def test_reject_nonempty_destination_without_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'local'
            dest.mkdir()
            sentinel = dest / 'keep.txt'
            sentinel.write_text('keep')
            with self.assertRaises(creation.InvalidIndexedCreation):
                creation.validate_indexed_creation(dest, [str(Path(temp) / 'nas')])
            self.assertEqual(sentinel.read_text(), 'keep')

    def test_reject_source_overlap(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'local'
            dest.mkdir()
            for root in (dest, dest / 'books', Path(temp)):
                with self.subTest(root=root):
                    with self.assertRaises(creation.InvalidIndexedCreation):
                        creation.validate_indexed_creation(dest, [str(root)])
            self.assertEqual(list(dest.iterdir()), [])

    def test_reject_unverified_storage(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'local'
            dest.mkdir()
            with patch.object(creation, 'require_local_indexed_storage',
                              side_effect=storage.UnverifiedIndexedStorage('network')):
                with self.assertRaises(storage.UnverifiedIndexedStorage):
                    creation.validate_indexed_creation(dest, [str(Path(temp) / 'nas')])
            self.assertEqual(list(dest.iterdir()), [])

    def test_reject_symlink_destination_and_relative_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'local'
            dest.mkdir()
            alias = Path(temp) / 'alias'
            alias.symlink_to(dest, target_is_directory=True)
            with self.assertRaises(creation.InvalidIndexedCreation):
                creation.validate_indexed_creation(alias, [str(Path(temp) / 'nas')])
            with self.assertRaises(creation.InvalidIndexedCreation):
                creation.validate_indexed_creation(dest, ['relative/books'])
            self.assertEqual(list(dest.iterdir()), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
