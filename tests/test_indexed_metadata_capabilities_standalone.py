#!/usr/bin/env python3
"""Test metadata capability discovery without loading Calibre or touching files."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'src/calibre/db/indexed_metadata_capabilities.py'
spec = importlib.util.spec_from_file_location('indexed_metadata_capabilities', FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FakePlugin:
    def __init__(self, name, file_types):
        self.name = name
        self.file_types = file_types


class IndexedMetadataCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        self.readers = [
            FakePlugin('EPUB Reader', {'EPUB'}),
            FakePlugin('Comic Reader', {'cbz', 'cbr'}),
            FakePlugin('Disabled Reader', {'pdf'}),
        ]
        self.writers = [
            FakePlugin('EPUB Writer', {'epub'}),
            FakePlugin('PDF Writer', {'PDF'}),
            FakePlugin('Disabled Writer', {'cbz'}),
        ]
        self.disabled = {'Disabled Reader', 'Disabled Writer'}

    def test_normalizes_format_and_lists_active_handlers(self):
        result = mod.metadata_capabilities(
            '.ePub', readers=self.readers, writers=self.writers,
            is_disabled=lambda plugin: plugin.name in self.disabled,
        )
        self.assertEqual(result, {
            'format': 'EPUB',
            'can_read_metadata': True,
            'can_write_metadata': True,
            'readers': ['EPUB Reader'],
            'writers': ['EPUB Writer'],
        })

    def test_read_only_and_write_only_formats(self):
        pdf = mod.metadata_capabilities(
            'pdf', readers=self.readers, writers=self.writers,
            is_disabled=lambda plugin: plugin.name in self.disabled,
        )
        self.assertFalse(pdf['can_read_metadata'])
        self.assertTrue(pdf['can_write_metadata'])
        cbr = mod.metadata_capabilities(
            'cbr', readers=self.readers, writers=self.writers,
            is_disabled=lambda plugin: plugin.name in self.disabled,
        )
        self.assertTrue(cbr['can_read_metadata'])
        self.assertFalse(cbr['can_write_metadata'])

    def test_disabled_plugins_are_not_reported(self):
        cbz = mod.metadata_capabilities(
            'cbz', readers=self.readers, writers=self.writers,
            is_disabled=lambda plugin: plugin.name in self.disabled,
        )
        self.assertTrue(cbz['can_read_metadata'])
        self.assertFalse(cbz['can_write_metadata'])
        self.assertEqual(cbz['writers'], [])

    def test_capabilities_for_multiple_formats(self):
        formats = mod.metadata_capabilities_for_formats(['EPUB', 'pdf', 'cbz', 'EPUB'])
        self.assertEqual(list(formats), ['CBZ', 'EPUB', 'PDF'])
        self.assertEqual(formats['EPUB']['format'], 'EPUB')
        self.assertTrue(formats['EPUB']['can_read_metadata'])
        self.assertTrue(formats['EPUB']['can_write_metadata'])

    def test_empty_format_is_rejected(self):
        with self.assertRaises(ValueError):
            mod.metadata_capabilities(' . ')


if __name__ == '__main__':
    unittest.main(verbosity=2)
