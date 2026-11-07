#!/usr/bin/env python3
"""Standalone tests for read-only Indexed Library filesystem discovery."""
import importlib.util
import os
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'src/calibre/db/indexed_file_discovery.py'
calibre = types.ModuleType('calibre')
ebooks = types.ModuleType('calibre.ebooks')
ebooks.BOOK_EXTENSIONS = ['epub', 'pdf', 'mobi', 'cbz']
calibre.__path__ = []
ebooks.__path__ = []
sys.modules.setdefault('calibre', calibre)
sys.modules['calibre.ebooks'] = ebooks
spec = importlib.util.spec_from_file_location('calibre.db.indexed_file_discovery', MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'source'
        (self.root / 'nested').mkdir(parents=True)
        (self.root / 'one.epub').write_bytes(b'epub bytes')
        (self.root / 'nested' / 'two.PDF').write_bytes(b'pdf bytes')
        (self.root / 'ignore.jpg').write_bytes(b'image')
        self.outside = Path(self.tmp.name) / 'outside.epub'
        self.outside.write_bytes(b'outside')
        self.before = {
            str(p): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in (self.root / 'one.epub', self.root / 'nested' / 'two.PDF', self.root / 'ignore.jpg')
        }

    def test_discovers_supported_files_recursively_and_read_only(self):
        files, errors = module.discover_ebook_files([str(self.root)])
        self.assertEqual(errors, [])
        self.assertEqual({x['format'] for x in files}, {'epub', 'pdf'})
        self.assertEqual({Path(x['path']).name for x in files}, {'one.epub', 'two.PDF'})
        for p, (raw, mtime) in self.before.items():
            self.assertEqual(Path(p).read_bytes(), raw)
            self.assertEqual(Path(p).stat().st_mtime_ns, mtime)

    def test_skips_file_and_directory_symlinks(self):
        (self.root / 'linked.epub').symlink_to(self.outside)
        (self.root / 'linked-dir').symlink_to(self.outside.parent, target_is_directory=True)
        files, errors = module.discover_ebook_files([str(self.root)])
        self.assertEqual(errors, [])
        self.assertEqual(len(files), 2)
        self.assertNotIn(str(self.outside), [x['path'] for x in files])

    def test_symlink_root_is_rejected_and_offline_root_reported(self):
        link = Path(self.tmp.name) / 'root-link'
        link.symlink_to(self.root, target_is_directory=True)
        missing = Path(self.tmp.name) / 'offline-nas'
        files, errors = module.discover_ebook_files([str(link), str(missing), str(self.root)])
        self.assertEqual(len(files), 2)
        self.assertEqual(len(errors), 2)

    def test_multiple_roots_deduplicate_paths(self):
        files, errors = module.discover_ebook_files([str(self.root), str(self.root)])
        self.assertEqual(errors, [])
        self.assertEqual(len(files), 2)

    def test_rejects_relative_roots(self):
        with self.assertRaises(ValueError):
            module.discover_ebook_files(['relative/path'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
