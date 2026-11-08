#!/usr/bin/env python
# License: GPLv3
"""Standalone regression tests for separated database path resolution."""
import json
import os
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch
from pathlib import Path

from calibre.db.separated_storage import CONFIG_NAME, configure_separated_storage, resolve_database_path


class SeparatedStorageTests(unittest.TestCase):
    def setUp(self):
        self.registry = {}
        mocked = patch('calibre.db.separated_storage.registry', return_value=self.registry)
        mocked.start()
        self.addCleanup(mocked.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'books'
        self.local = Path(self.tmp.name) / 'local-db'
        self.root.mkdir()
        self.local.mkdir()

    def configure(self, database_directory, version=1):
        (self.root / CONFIG_NAME).write_text(
            json.dumps({'version': version, 'database_directory': str(database_directory)}),
            encoding='utf-8',
        )

    def test_unconfigured_library_keeps_standard_database_location(self):
        self.assertEqual(resolve_database_path(str(self.root)), str(self.root / 'metadata.db'))

    def test_separated_library_resolves_local_database(self):
        self.configure(self.local)
        self.assertEqual(resolve_database_path(str(self.root)), str(self.local / 'metadata.db'))

    def test_missing_local_directory_fails_closed(self):
        self.configure(self.local / 'missing')
        with self.assertRaises(FileNotFoundError):
            resolve_database_path(str(self.root))

    def test_relative_database_directory_rejected(self):
        self.configure('relative/path')
        with self.assertRaises(ValueError):
            resolve_database_path(str(self.root))

    def test_same_root_rejected(self):
        self.configure(self.root)
        with self.assertRaises(ValueError):
            resolve_database_path(str(self.root))

    def test_existing_books_root_database_is_not_shadowed(self):
        self.configure(self.local)
        (self.root / 'metadata.db').write_bytes(b'placeholder')
        with self.assertRaises(FileExistsError):
            resolve_database_path(str(self.root))

    def test_invalid_json_is_not_silently_ignored(self):
        (self.root / CONFIG_NAME).write_text('{invalid', encoding='utf-8')
        with self.assertRaises(json.JSONDecodeError):
            resolve_database_path(str(self.root))

    def test_create_separated_library_configuration(self):
        expected = configure_separated_storage(str(self.root), str(self.local))
        self.assertEqual(expected, str(self.local / 'metadata.db'))
        self.assertEqual(resolve_database_path(str(self.root)), expected)

    def test_create_refuses_existing_database(self):
        (self.root / 'metadata.db').write_bytes(b'existing')
        with self.assertRaises(FileExistsError):
            configure_separated_storage(str(self.root), str(self.local))
        self.assertFalse((self.root / CONFIG_NAME).exists())

    def test_create_refuses_existing_target_database(self):
        (self.local / 'metadata.db').write_bytes(b'existing')
        with self.assertRaises(FileExistsError):
            configure_separated_storage(str(self.root), str(self.local))
        self.assertFalse((self.root / CONFIG_NAME).exists())

    def test_create_refuses_overwriting_marker(self):
        configure_separated_storage(str(self.root), str(self.local))
        with self.assertRaises(FileExistsError):
            configure_separated_storage(str(self.root), str(self.local))

    def test_nested_storage_directories_rejected(self):
        nested = self.root / 'database'
        nested.mkdir()
        with self.assertRaises(ValueError):
            configure_separated_storage(str(self.root), str(nested))

    def test_nonempty_books_folder_rejected(self):
        (self.root / 'existing-book.txt').write_text('user data')
        with self.assertRaises(FileExistsError):
            configure_separated_storage(str(self.root), str(self.local))
        self.assertFalse((self.root / CONFIG_NAME).exists())

    def test_unwritable_database_rejected(self):
        self.configure(self.local)
        with patch('calibre.db.separated_storage.os.access', return_value=False):
            with self.assertRaises(PermissionError):
                resolve_database_path(str(self.root))

    def test_database_folder_cannot_be_shared_by_two_libraries(self):
        configure_separated_storage(str(self.root), str(self.local))
        other = self.root.with_name('other-books')
        other.mkdir()
        with self.assertRaises(FileExistsError):
            configure_separated_storage(str(other), str(self.local))
        self.assertFalse((other / CONFIG_NAME).exists())

    def test_unknown_config_version_rejected(self):
        self.configure(self.local, version=2)
        with self.assertRaises(ValueError):
            resolve_database_path(str(self.root))


class SeparatedOperationsTests(unittest.TestCase):
    setUp = SeparatedStorageTests.setUp
    def open_library(self):
        from calibre.db.backend import DB
        from calibre.db.cache import Cache
        cache = Cache(DB(str(self.root)))
        cache.init()
        self.addCleanup(cache.close)
        return cache

    def create_book(self, cache):
        from calibre.ebooks.metadata.book.base import Metadata
        book = cache.create_book_entry(Metadata('Original title', ['Original author']))
        self.assertTrue(cache.add_format(book, 'TXT', BytesIO(b'original book'), run_hooks=False))
        return book

    def test_managed_operations_and_reopen(self):
        from calibre.db.tests.base import IMG
        from calibre.db.legacy import LibraryDatabase
        configure_separated_storage(str(self.root), str(self.local))
        cache = self.open_library()
        book = self.create_book(cache)
        self.assertTrue(LibraryDatabase.exists_at(str(self.root)))
        self.assertTrue((self.local / 'metadata.db').is_file())
        self.assertFalse(LibraryDatabase.exists_at(str(self.local)))
        self.assertFalse((self.root / 'metadata.db').exists())
        old_path = cache.format_abspath(book, 'TXT')
        cache.set_cover({book: IMG})
        cache.set_field('title', {book: 'Changed title'})
        cache.set_field('authors', {book: ['Changed author']})
        cache.set_field('series', {book: 'Series'})
        cache.set_field('tags', {book: ['Collection']})
        self.assertFalse(os.path.exists(old_path))
        self.assertEqual(cache.format(book, 'TXT'), b'original book')
        self.assertIsNotNone(cache.cover(book))
        cache.dump_metadata()
        self.assertTrue(list(self.root.rglob('metadata.opf')))
        cache.close()
        reopened = self.open_library()
        self.assertEqual(reopened.field_for('title', book), 'Changed title')
        self.assertEqual(reopened.format(book, 'TXT'), b'original book')
        reopened.remove_books({book})
        self.assertNotIn(book, reopened.all_book_ids())
        self.assertFalse(list(self.root.glob('*/*/*.txt')))

    def test_disconnected_storage_rejects_writes_and_reopen(self):
        configure_separated_storage(str(self.root), str(self.local))
        cache = self.open_library()
        book = self.create_book(cache)
        mounted = self.root.with_name('offline-books')
        self.root.rename(mounted)
        self.root.mkdir()  # Empty underlying mountpoint must never receive books.
        try:
            for operation in (
                lambda: cache.set_field('title', {book: 'Must not change'}),
                lambda: cache.add_format(book, 'TXT', BytesIO(b'replacement'), run_hooks=False),
                lambda: cache.remove_books({book}),
                lambda: self.open_library(),
            ):
                with self.assertRaises(OSError):
                    operation()
            self.assertEqual(list(self.root.iterdir()), [])
        finally:
            self.root.rmdir()
            mounted.rename(self.root)
        self.assertEqual(cache.field_for('title', book), 'Original title')
        self.assertEqual(cache.format(book, 'TXT'), b'original book')

    def test_missing_database_is_not_reinitialized(self):
        configure_separated_storage(str(self.root), str(self.local))
        cache = self.open_library()
        cache.close()
        (self.local / 'metadata.db').rename(self.local / 'offline.db')
        self.registry.clear()  # The on-storage marker also protects a fresh installation.
        with self.assertRaises(FileNotFoundError):
            self.open_library()
        self.assertFalse((self.local / 'metadata.db').exists())

    def test_books_root_relocation_keeps_database_local(self):
        configure_separated_storage(str(self.root), str(self.local))
        cache = self.open_library()
        book = self.create_book(cache)
        destination = self.root.with_name('relocated-books')
        cache.move_library_to(str(destination))
        self.assertEqual(cache.dbpath, str(self.local / 'metadata.db'))
        self.assertTrue((destination / CONFIG_NAME).is_file())
        self.assertEqual(cache.format(book, 'TXT'), b'original book')
        cache.close()
        self.root = destination
        reopened = self.open_library()
        self.assertEqual(reopened.format(book, 'TXT'), b'original book')

    def test_restore_database_from_book_sidecars(self):
        from calibre.db.restore import Restore
        configure_separated_storage(str(self.root), str(self.local))
        cache = self.open_library()
        book = self.create_book(cache)
        cache.set_field('tags', {book: ['Collection']})
        author = cache.get_item_id('authors', 'Original author')
        cache.set_notes_for('authors', author, '<p>Author note</p>')
        cache.dump_metadata()
        cache.close()
        restorer = Restore(str(self.root))
        restorer.run()
        self.assertIsNone(restorer.tb, restorer.tb)
        reopened = self.open_library()
        self.assertEqual(reopened.format(book, 'TXT'), b'original book')
        self.assertEqual(reopened.field_for('tags', book), ('Collection',))
        author = reopened.get_item_id('authors', 'Original author')
        self.assertEqual(reopened.notes_for('authors', author), '<p>Author note</p>')
        self.assertTrue((self.local / 'metadata_pre_restore.db').is_file())
        self.assertFalse((self.root / 'metadata.db').exists())

    def test_move_book_between_libraries(self):
        from calibre.db.backend import DB
        from calibre.db.cache import Cache
        from calibre.db.copy_to_library import copy_one_book
        configure_separated_storage(str(self.root), str(self.local))
        source = self.open_library()
        book = self.create_book(source)
        destination = Cache(DB(str(self.root.with_name('destination'))))
        destination.init()
        self.addCleanup(destination.close)
        result = copy_one_book(book, source, destination)
        self.assertEqual(destination.format(result['new_book_id'], 'TXT'), b'original book')
        source.remove_books({book})
        self.assertNotIn(book, source.all_book_ids())

    def test_creation_dialog_and_switch_to_existing(self):
        from types import SimpleNamespace

        from calibre.db.backend import DB
        from calibre.gui2 import Application
        from calibre.gui2.dialogs.choose_library import ChooseLibrary
        app = Application.instance() or Application([])
        self.assertIsNotNone(app)
        current = SimpleNamespace(library_path=str(self.root.with_name('current')), exists_at=DB.exists_at)
        opened = []

        def callback(path, **kwargs):
            self.assertEqual(path, str(self.root))
            opened.append(self.open_library())

        def error(*args, **kwargs):
            self.fail(str(args))

        with patch('calibre.gui2.dialogs.choose_library.error_dialog', side_effect=error):
            dialog = ChooseLibrary(current, callback, None)
            dialog.empty_library.setChecked(True)
            dialog.location.setText(str(self.root))
            dialog.separate_storage.setChecked(True)
            dialog.database_location.setText(str(self.local))
            dialog.accept()
            self.assertEqual(len(opened), 1)
            self.create_book(opened[0])
            opened[0].close()
            existing = ChooseLibrary(current, callback, None)
            existing.location.setText(str(self.root))
            existing.accept()
            self.assertEqual(len(opened), 2)
            self.assertEqual(len(opened[1].all_book_ids()), 1)

    def test_welcome_wizard_creation(self):
        from calibre.gui2 import Application
        from calibre.gui2.wizard import LibraryPage
        app = Application.instance() or Application([])
        self.assertIsNotNone(app)
        page = LibraryPage()
        page.default_library_name = None
        page.location.setText(str(self.root))
        page.separate_storage.setChecked(True)
        page.database_location.setText(str(self.local))
        self.assertTrue(page.validatePage())
        with patch('calibre.gui2.wizard.prefs', {}):
            page.commit()
        cache = self.open_library()
        self.assertEqual(cache.dbpath, str(self.local / 'metadata.db'))
        self.create_book(cache)

    def test_local_database_disconnection_and_close(self):
        configure_separated_storage(str(self.root), str(self.local))
        cache = self.open_library()
        book = self.create_book(cache)
        offline = self.local.with_name('offline-local')
        self.local.rename(offline)
        try:
            with self.assertRaises(OSError):
                cache.set_field('title', {book: 'Unavailable'})
            with self.assertRaises(OSError):
                self.open_library()
            cache.close()
        finally:
            offline.rename(self.local)
        reopened = self.open_library()
        self.assertEqual(reopened.field_for('title', book), 'Original title')

    def test_database_backup_remains_local(self):
        configure_separated_storage(str(self.root), str(self.local))
        cache = self.open_library()
        book = self.create_book(cache)
        self.assertEqual(cache.format(book, 'TXT'), b'original book')
        backup = self.local / 'backup.db'
        cache.backend.backup_database(str(backup))
        self.assertTrue(backup.is_file())
        self.assertFalse((self.root / 'metadata.db').exists())

    def test_database_sql_rebuild_remains_local(self):
        try:
            from apsw import shell
        except ImportError:
            self.skipTest('APSW shell module is unavailable in the installed runtime')
        del shell
        configure_separated_storage(str(self.root), str(self.local))
        cache = self.open_library()
        book = self.create_book(cache)
        cache.dump_and_restore()
        self.assertEqual(cache.format(book, 'TXT'), b'original book')
        self.assertTrue((self.local / 'metadata.db').is_file())
        self.assertFalse((self.root / 'metadata.db').exists())

    def test_startup_does_not_recreate_disconnected_books_root(self):
        from types import SimpleNamespace

        from calibre.gui2.main import AbortInit, get_library_path
        configure_separated_storage(str(self.root), str(self.local))
        offline = self.root.with_name('offline-books')
        self.root.rename(offline)
        errors = []
        runner = SimpleNamespace(show_error=lambda *args, **kwargs: errors.append(args))
        try:
            with patch('calibre.gui2.main.prefs', {'library_path': str(self.root)}):
                with self.assertRaises(AbortInit):
                    get_library_path(runner)
            self.assertFalse(self.root.exists())
            self.assertEqual(len(errors), 1)
        finally:
            offline.rename(self.root)

    def test_standard_library_operations(self):
        cache = self.open_library()
        book = self.create_book(cache)
        self.assertTrue((self.root / 'metadata.db').exists())
        cache.set_field('title', {book: 'Ordinary title'})
        self.assertEqual(cache.format(book, 'TXT'), b'original book')
        cache.remove_books({book})
        self.assertNotIn(book, cache.all_book_ids())


if __name__ == '__main__':
    unittest.main()
