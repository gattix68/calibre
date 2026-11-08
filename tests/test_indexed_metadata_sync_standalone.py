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


class FakeMetadata:
    def __init__(self, **values):
        object.__setattr__(self, 'values', values)

    def __setattr__(self, name, value):
        if name == 'values':
            object.__setattr__(self, name, value)
        else:
            self.values[name] = value

    def is_null(self, field):
        return field not in self.values or self.values[field] is None

    def get(self, field, default=None):
        return self.values.get(field, default)

    def deepcopy(self):
        return FakeMetadata(**dict(self.values))


class IndexedMetadataReadTests(unittest.TestCase):
    def test_compares_only_present_embedded_values(self):
        database = FakeMetadata(title='Old Title', authors=['A. Author'], tags=['Fiction'], comments='Local note')
        embedded = FakeMetadata(title='New Title', authors=['A. Author'], tags=None)
        differences = mod.compare_metadata(database, embedded)
        self.assertEqual(set(differences), {'title'})
        self.assertEqual(differences['title'], {'database': 'Old Title', 'embedded': 'New Title'})

    def test_compares_structured_values_and_dates(self):
        import datetime
        database = FakeMetadata(
            pubdate=datetime.datetime(2020, 1, 1),
            identifiers={'isbn': '123'},
            languages=['eng', 'fra'],
        )
        embedded = FakeMetadata(
            pubdate=datetime.datetime(2021, 1, 1),
            identifiers={'isbn': '456'},
            languages=['eng', 'fra'],
        )
        differences = mod.compare_metadata(database, embedded)
        self.assertEqual(set(differences), {'pubdate', 'identifiers'})

    def test_merge_returns_clone_and_applies_only_differences(self):
        database = FakeMetadata(title='Old Title', authors=['A. Author'], tags=['Fiction'])
        embedded = FakeMetadata(title='New Title', authors=['A. Author'], tags=None)
        updated, differences = mod.merge_embedded_metadata(database, embedded)
        self.assertEqual(updated.values, {'title': 'New Title', 'authors': ['A. Author'], 'tags': ['Fiction']})
        self.assertEqual(set(differences), {'title'})
        self.assertEqual(database.values['title'], 'Old Title')
        self.assertEqual(embedded.values['title'], 'New Title')
        self.assertIsNot(updated, database)

    def test_sync_plan_accepts_agreement_across_formats(self):
        database = FakeMetadata(title='Old', publisher='Old Publisher')
        epub = FakeMetadata(title='New', publisher='New Publisher')
        pdf = FakeMetadata(title='New', publisher='New Publisher')
        updated, plan = mod.plan_embedded_metadata_sync(database, {'EPUB': epub, 'PDF': pdf})
        self.assertEqual(updated.values['title'], 'New')
        self.assertEqual(updated.values['publisher'], 'New Publisher')
        self.assertEqual(set(plan['updates']), {'title', 'publisher'})
        self.assertEqual(plan['conflicts'], {})
        self.assertEqual(database.values['title'], 'Old')

    def test_sync_plan_reports_conflicting_format_values(self):
        database = FakeMetadata(title='Old', publisher='Old Publisher')
        epub = FakeMetadata(title='EPUB Title', publisher='Shared Publisher')
        pdf = FakeMetadata(title='PDF Title', publisher='Shared Publisher')
        updated, plan = mod.plan_embedded_metadata_sync(database, {'EPUB': epub, 'PDF': pdf})
        self.assertEqual(updated.values['title'], 'Old')
        self.assertEqual(updated.values['publisher'], 'Shared Publisher')
        self.assertIn('title', plan['conflicts'])
        self.assertEqual(len(plan['conflicts']['title']), 2)
        self.assertEqual(database.values['title'], 'Old')

    def test_comparison_does_not_modify_metadata_objects(self):
        database = FakeMetadata(title='Database Title')
        embedded = FakeMetadata(title='File Title')
        before_database = dict(database.values)
        before_embedded = dict(embedded.values)
        mod.compare_metadata(database, embedded)
        self.assertEqual(database.values, before_database)
        self.assertEqual(embedded.values, before_embedded)

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

    def test_detects_size_and_mtime_changes(self):
        from types import SimpleNamespace
        unchanged = SimpleNamespace(st_size=100, st_mtime_ns=500)
        changed_size = SimpleNamespace(st_size=101, st_mtime_ns=500)
        changed_time = SimpleNamespace(st_size=100, st_mtime_ns=501)
        self.assertFalse(mod.indexed_file_has_changed(100, 500, unchanged))
        self.assertTrue(mod.indexed_file_has_changed(100, 500, changed_size))
        self.assertTrue(mod.indexed_file_has_changed(100, 500, changed_time))

    def test_atomic_transform_replaces_bytes_without_changing_path(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'book.epub'
            path.write_bytes(b'original')
            result = mod.apply_to_indexed_file_atomically(
                str(path),
                lambda stream: (stream.write(b'updated'), 'written')[1],
            )
            self.assertEqual(result, 'written')
            self.assertEqual(path.name, 'book.epub')
            self.assertEqual(path.read_bytes(), b'updated')
            self.assertFalse(list(Path(temp).glob('.calibre-indexed-*')))

    def test_failed_atomic_transform_preserves_original_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'book.epub'
            path.write_bytes(b'original')
            def fail(stream):
                stream.write(b'partial')
                raise RuntimeError('simulated metadata writer failure')
            with self.assertRaises(RuntimeError):
                mod.apply_to_indexed_file_atomically(str(path), fail)
            self.assertEqual(path.read_bytes(), b'original')
            self.assertFalse(list(Path(temp).glob('.calibre-indexed-*')))

    def test_rejects_empty_format(self):
        with self.assertRaises(ValueError):
            mod.read_embedded_metadata('/unused.epub', ' . ', metadata_reader=lambda *_: None)


if __name__ == '__main__':
    unittest.main(verbosity=2)
