#!/usr/bin/env python3
"""Standalone tests for conservative Indexed Library registration planning."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'src/calibre/db/indexed_library_registration.py'
spec = importlib.util.spec_from_file_location('indexed_library_registration', FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class RegistrationPlanTests(unittest.TestCase):
    def record(self, path, fmt, metadata=None, **extra):
        return {
            'file_path': path, 'format': fmt, 'file_size': 100,
            'modified_time_ns': 123, 'metadata': metadata, **extra,
        }

    def test_groups_same_basename_formats_in_same_folder(self):
        scan = {'files': [
            self.record('/nas/books/Novel.epub', 'EPUB', {'title': 'Novel', 'authors': ['A']}),
            self.record('/nas/books/Novel.pdf', 'PDF', {'title': 'Novel', 'authors': ['A']}),
            self.record('/nas/books/Other.epub', 'EPUB', {'title': 'Other'}),
            self.record('/nas/other/Novel.epub', 'EPUB', {'title': 'Novel'}),
        ]}
        plan = mod.build_indexed_registration_plan(scan)
        self.assertEqual(plan['book_count'], 3)
        novel = next(b for b in plan['books']
                     if b['group_key']['directory'] == '/nas/books'
                     and b['group_key']['filename_stem'] == 'novel')
        self.assertEqual([f['format'] for f in novel['formats']], ['EPUB', 'PDF'])
        self.assertFalse(novel['requires_review'])
        self.assertEqual(novel['proposed_metadata']['title'], 'Novel')

    def test_reports_metadata_disagreement_instead_of_merging(self):
        scan = {'files': [
            self.record('/nas/Book.epub', 'EPUB', {'title': 'Correct Title', 'authors': ['A']}),
            self.record('/nas/Book.pdf', 'PDF', {'title': 'Different Title', 'authors': ['A']}),
        ]}
        book = mod.build_indexed_registration_plan(scan)['books'][0]
        self.assertTrue(book['requires_review'])
        self.assertEqual(book['proposed_metadata']['title'], 'Correct Title')
        self.assertIn('title', book['metadata_conflicts'])
        self.assertEqual(len(book['metadata_conflicts']['title']), 2)

    def test_duplicate_same_format_is_not_silently_registered(self):
        scan = {'files': [
            self.record('/nas/Book.epub', 'EPUB', {'title': 'Book'}),
            self.record('/nas/sub/Book.epub', 'EPUB', {'title': 'Book'}),
        ]}
        plan = mod.build_indexed_registration_plan(scan)
        self.assertEqual(plan['book_count'], 2)
        self.assertTrue(all(not b['duplicate_formats'] for b in plan['books']))
        same_dir = {'files': [
            self.record('/nas/Book.epub', 'EPUB', {'title': 'Book'}),
            self.record('/nas/Book.EPUB', 'EPUB', {'title': 'Book copy'}),
        ]}
        book = mod.build_indexed_registration_plan(same_dir)['books'][0]
        self.assertTrue(book['duplicate_formats'])
        self.assertTrue(book['requires_review'])
        self.assertEqual(book['formats'], [])

    def test_requires_review_when_no_readable_metadata_exists(self):
        scan = {'files': [
            self.record('/nas/Comic.cbz', 'CBZ', None, error='metadata unreadable'),
        ], 'errors': [{'file_path': '/nas/Comic.cbz', 'error': 'metadata unreadable'}]}
        plan = mod.build_indexed_registration_plan(scan)
        self.assertTrue(plan['books'][0]['requires_review'])
        self.assertEqual(plan['books'][0]['proposed_metadata'], {})
        self.assertEqual(len(plan['scan_errors']), 1)

    def test_invalid_records_are_reported_and_input_is_not_modified(self):
        valid = self.record('/nas/Book.epub', 'EPUB', {'title': 'Book'})
        invalid = {'file_path': 'relative/book.epub', 'format': 'EPUB'}
        scan = {'files': [valid, invalid], 'errors': [], 'skipped': []}
        before = repr(scan)
        plan = mod.build_indexed_registration_plan(scan)
        self.assertEqual(len(plan['invalid_records']), 1)
        self.assertEqual(plan['book_count'], 1)
        self.assertEqual(repr(scan), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
