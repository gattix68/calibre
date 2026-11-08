#!/usr/bin/env python3
"""Test read-only embedded metadata extraction without loading Calibre."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'src/calibre/db/indexed_metadata_sync.py'
spec = importlib.util.spec_from_file_location('indexed_metadata_sync', FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class IndexedMetadataReadTests(unittest.TestCase):
    def test_uses_format_reader_on_read_only_stream(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'book.epub'
            path.write_bytes(b'fake epub bytes')
            seen = {}

            def reader(stream, fmt):
                seen['format'] = fmt
                seen['mode'] = stream.mode
                seen['data'] = stream.read()
                return {'title': 'Example'}

            result = mod.read_embedded_metadata(str(path), '.EPUB', metadata_reader=reader)
            self.assertEqual(result, {'title': 'Example'})
            self.assertEqual(seen, {
                'format': 'epub',
                'mode': 'rb',
                'data': b'fake epub bytes',
            })
            self.assertEqual(path.read_bytes(), b'fake epub bytes')

    def test_rejects_format_extension_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'book.pdf'
            path.write_bytes(b'pdf')
            with self.assertRaises(ValueError):
                mod.read_embedded_metadata(str(path), 'epub', metadata_reader=lambda *_: None)

    def test_rejects_symlinks_and_missing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'target.epub'
            target.write_bytes(b'epub')
            link = root / 'link.epub'
            link.symlink_to(target)
            with self.assertRaises(OSError):
                mod.read_embedded_metadata(str(link), 'epub', metadata_reader=lambda *_: None)
            with self.assertRaises(OSError):
                mod.read_embedded_metadata(str(root / 'missing.epub'), 'epub', metadata_reader=lambda *_: None)

    def test_rejects_empty_format(self):
        with self.assertRaises(ValueError):
            mod.read_embedded_metadata('/unused.epub', ' . ', metadata_reader=lambda *_: None)


if __name__ == '__main__':
    unittest.main(verbosity=2)
