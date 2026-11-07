#!/usr/bin/env python3
"""Isolated Indexed Library startup tests; no Calibre imports or NAS access."""
import ast
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'src/calibre/db/indexed_library_config.py'
BACKEND = ROOT / 'src/calibre/db/backend.py'

spec = importlib.util.spec_from_file_location('indexed_library_config', CONFIG)
config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_module)


def startup_guard():
    tree = ast.parse(BACKEND.read_text(encoding='utf-8'))
    db = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DB')
    constructor = next(n for n in db.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
    guard = next(n for n in constructor.body if isinstance(n, ast.If)
                 and isinstance(n.test, ast.Compare)
                 and isinstance(n.test.left, ast.Name)
                 and n.test.left.id == 'indexed_config')
    return compile(ast.Module(body=[guard], type_ignores=[]), '<indexed-startup-guard>', 'exec')


class IndexedLibraryStartupTests(unittest.TestCase):
    def test_local_database_path_resolution(self):
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / 'local-library'
            library.mkdir()
            with self.assertRaises(config_module.InvalidIndexedLibraryConfig):
                config_module.indexed_database_path(library)

            marker = library / config_module.CONFIG_FILENAME
            marker.write_text(json.dumps({
                'version': 1, 'mode': 'indexed',
                'source_roots': ['/nonexistent/offline-nas/books'],
            }), encoding='utf-8')
            expected = library / 'metadata.db'
            self.assertEqual(config_module.indexed_database_path(library), expected)
            self.assertFalse(expected.exists())

            marker.write_text('{"version":1,"mode":"managed","source_roots":[]}', encoding='utf-8')
            with self.assertRaises(config_module.InvalidIndexedLibraryConfig):
                config_module.indexed_database_path(library)
            self.assertFalse(expected.exists())

    def test_modes_and_offline_root(self):
        guard = startup_guard()
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp)
            marker = library / config_module.CONFIG_FILENAME
            self.assertIsNone(config_module.load_indexed_library_config(library))
            exec(guard, {'indexed_config': None})

            cfg = {'version': 1, 'mode': 'indexed',
                   'source_roots': ['/nonexistent/offline-nas/books']}
            marker.write_text(json.dumps(cfg), encoding='utf-8')
            loaded = config_module.load_indexed_library_config(library)
            self.assertEqual(loaded, cfg)
            with self.assertRaisesRegex(RuntimeError, 'not yet available'):
                exec(guard, {'indexed_config': loaded, 'indexed_database_path': config_module.indexed_database_path})
            self.assertFalse((library / 'metadata.db').exists())

            marker.write_text('{"mode":"invalid"}', encoding='utf-8')
            with self.assertRaises(config_module.InvalidIndexedLibraryConfig):
                config_module.load_indexed_library_config(library)
            self.assertFalse((library / 'metadata.db').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
