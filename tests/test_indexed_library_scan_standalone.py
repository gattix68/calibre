#!/usr/bin/env python3
"""Standalone tests for read-only Indexed Library source discovery."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'src/calibre/db/indexed_library_scan.py'
spec = importlib.util.spec_from_file_location('indexed_library_scan', FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class IndexedLibraryScanTests(unittest.TestCase):
    def test_discovers_supported_files_recursively_without_modifying_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'source'
            nested = root / 'Publisher' / 'Series'
            nested.mkdir(parents=True)
            epub = nested / 'Book.epub'
            cbz = nested / 'Issue.cbz'
            other = nested / 'notes.txt'
            epub.write_bytes(b'epub data')
            cbz.write_bytes(b'cbz data')
            other.write_bytes(b'leave alone')
            before = {p: p.read_bytes() for p in (epub, cbz, other)}
            def reader(stream, fmt):
                return {'format': fmt, 'size': len(stream.read())}
            result = mod.scan_indexed_source_roots(
                [str(root)], {'epub', 'cbz'}, metadata_reader=reader
            )
            self.assertEqual([Path(x['file_path']).name for x in result['files']],
                             ['Book.epub', 'Issue.cbz'])
            self.assertEqual(result['files'][0]['relative_path'],
                             'Publisher/Series/Book.epub')
            self.assertEqual(result['files'][0]['metadata'],
                             {'format': 'epub', 'size': len(b'epub data')})
            self.assertEqual(result['errors'], [])
            self.assertEqual(result['skipped'], [])
            self.assertEqual({p: p.read_bytes() for p in before}, before)
            self.assertEqual(sorted(p.name for p in nested.iterdir()),
                             ['Book.epub', 'Issue.cbz', 'notes.txt'])

    def test_skips_file_and_directory_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'source'
            root.mkdir()
            target = Path(temp) / 'outside.epub'
            target.write_bytes(b'outside')
            (root / 'linked.epub').symlink_to(target)
            outside_dir = Path(temp) / 'outside-dir'
            outside_dir.mkdir()
            (outside_dir / 'hidden.epub').write_bytes(b'hidden')
            (root / 'linked-dir').symlink_to(outside_dir, target_is_directory=True)
            result = mod.scan_indexed_source_roots(
                [str(root)], {'epub'}, metadata_reader=lambda *_: {'title': 'x'}
            )
            self.assertEqual(result['files'], [])
            self.assertEqual(len(result['skipped']), 2)
            self.assertEqual(target.read_bytes(), b'outside')
            self.assertTrue((outside_dir / 'hidden.epub').exists())

    def test_reports_reader_errors_but_keeps_file_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            book = root / 'book.pdf'
            book.write_bytes(b'pdf')
            def fail(*args):
                raise ValueError('unsupported metadata')
            result = mod.scan_indexed_source_roots([str(root)], {'pdf'}, metadata_reader=fail)
            self.assertEqual(len(result['files']), 1)
            self.assertIsNone(result['files'][0]['metadata'])
            self.assertIn('unsupported metadata', result['files'][0]['error'])
            self.assertEqual(len(result['errors']), 1)

    def test_rejects_empty_formats_and_relative_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                mod.scan_indexed_source_roots([temp], set(), metadata_reader=lambda *_: None)
            with self.assertRaises(ValueError):
                mod.scan_indexed_source_roots(['relative/path'], {'epub'}, metadata_reader=lambda *_: None)

    def test_reports_missing_roots_without_creating_them(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / 'missing'
            result = mod.scan_indexed_source_roots(
                [str(missing)], {'epub'}, metadata_reader=lambda *_: None
            )
            self.assertEqual(result['files'], [])
            self.assertEqual(len(result['errors']), 1)
            self.assertFalse(missing.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
