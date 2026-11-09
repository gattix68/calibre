#!/usr/bin/env python
# License: GPLv3
"""Phase 1 architecture regressions; all paths are disposable fixtures."""

import errno
import json
import ntpath
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import Mock, patch

from calibre.db import separated_storage as storage
from calibre.db.tests import test_separated_storage as shared


class FinalReviewTests(unittest.TestCase):
    setUp = shared.SeparatedStorageTests.setUp

    def configure(self):
        storage.configure_separated_storage(str(self.root), str(self.local))

    def test_null_marker_is_not_an_ordinary_library(self):
        (self.root / storage.CONFIG_NAME).write_text('null', encoding='utf-8')
        with self.assertRaises(ValueError):
            storage.resolve_database_path(str(self.root))
        self.assertFalse((self.root / 'metadata.db').exists())

    def test_marker_field_types_fail_closed(self):
        valid = {'version': 1, 'database_directory': str(self.local)}
        for field, values in (
            ('version', (True, 1.0, '1')),
            ('storage_id', (None, False, [], '', 42)),
            ('initialized', ('false', 0, 1, None, [])),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    self.registry.clear()
                    config = dict(valid, **{field: value})
                    (self.root / storage.CONFIG_NAME).write_text(json.dumps(config), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        storage.resolve_database_path(str(self.root))
                    self.assertEqual(self.registry, {})
        self.assertFalse((self.root / 'metadata.db').exists())

    def test_resolver_rejects_nested_database_configuration(self):
        nested = self.root / 'database'
        nested.mkdir()
        (self.root / storage.CONFIG_NAME).write_text(
            json.dumps({
                'version': 1,
                'database_directory': str(nested),
            }),
            encoding='utf-8',
        )
        with self.assertRaises(ValueError):
            storage.resolve_database_path(str(self.root))

    def test_windows_nesting_checks_are_case_insensitive(self):
        # Lexical Windows semantics only: never probe a real UNC server, even
        # when this regression is run on Windows.
        paths = SimpleNamespace(realpath=ntpath.normpath, commonpath=ntpath.commonpath, normcase=ntpath.normcase)
        with patch('calibre.db.separated_storage.os', SimpleNamespace(path=paths)):
            for books, database in ((r'C:\Data\Books', r'c:\DATA'), (r'C:\Data', r'c:\DATA\Database')):
                with self.subTest(books=books, database=database):
                    with self.assertRaises(ValueError):
                        storage.validate_directories(books, database)
            storage.validate_directories(r'C:\Books', r'D:\Database')
            storage.validate_directories(r'\\server\share\Books', r'C:\Database')

    def test_urls_are_rejected_before_path_resolution_or_creation(self):
        for uri in ('smb://example.invalid/share/Books', 'file:///tmp/Books', 'https://example.invalid/Books'):
            with self.subTest(uri=uri):
                with self.assertRaises(ValueError):
                    storage.resolve_database_path(uri)
                with self.assertRaises(ValueError):
                    storage.configure_separated_storage(uri, str(self.local))
        storage.validate_filesystem_path(r'C:\Books')
        storage.validate_filesystem_path('C://Books')
        storage.validate_filesystem_path(r'\\server\share\Books')

    @shared.isolated_gui_test
    def test_creation_dialog_rejects_smb_url_without_creating_directories(self):
        from calibre.db.backend import DB
        from calibre.gui2 import Application
        from calibre.gui2.dialogs.choose_library import ChooseLibrary

        app = Application.instance() or Application([])
        self.assertIsNotNone(app)
        callback = Mock()
        current = SimpleNamespace(library_path=str(self.root), exists_at=DB.exists_at)
        dialog = ChooseLibrary(current, callback, None)
        dialog.empty_library.setChecked(True)
        dialog.location.setText('smb://example.invalid/share/Books')
        with patch('calibre.gui2.dialogs.choose_library.error_dialog') as errors, patch('calibre.gui2.dialogs.choose_library.os.makedirs') as mkdir:
            dialog.accept()
        errors.assert_called_once()
        mkdir.assert_not_called()
        callback.assert_not_called()

    @shared.isolated_gui_test
    def test_wizard_rejects_smb_url_before_directory_creation(self):
        from calibre.gui2 import Application
        from calibre.gui2.wizard import LibraryPage

        app = Application.instance() or Application([])
        self.assertIsNotNone(app)
        page = LibraryPage()
        page.location.setText('smb://example.invalid/share/Books')
        with patch('calibre.gui2.wizard.error_dialog') as errors, patch('calibre.gui2.wizard.os.makedirs') as mkdir:
            self.assertFalse(page.validatePage())
            with self.assertRaises(ValueError):
                page.commit()
        errors.assert_called_once()
        mkdir.assert_not_called()

    def test_library_checker_missing_book_directory_is_not_a_format_repair(self):
        from calibre.library.check_library import CheckLibrary

        db = self.open_legacy_api()
        book_directory = self.root / db.new_api.field_for('path', 1)
        hidden = self.root.with_name('temporarily-unavailable-book')
        book_directory.rename(hidden)
        try:
            checker = CheckLibrary(str(self.root), db)
            checker.scan_library((), ())
            self.assertTrue(checker.failed_folders)
            self.assertEqual(checker.missing_formats, [])
            self.assertEqual(db.new_api.formats(1, verify_formats=False), ('TXT',))
        finally:
            hidden.rename(book_directory)

    def open_legacy_api(self):
        from calibre.db.legacy import LibraryDatabase

        self.configure()
        db = LibraryDatabase(str(self.root))
        self.addCleanup(db.close)
        shared.SeparatedOperationsTests.create_book(self, db.new_api)
        return db

    def test_library_checker_preserves_storage_marker(self):
        from calibre.library.check_library import CheckLibrary

        db = self.open_legacy_api()
        checker = CheckLibrary(str(self.root), db)
        checker.scan_library((), ())
        self.assertEqual(checker.invalid_authors, [])
        self.assertEqual(checker.extra_authors, [])
        self.assertEqual(checker.missing_formats, [])
        self.assertTrue((self.root / storage.CONFIG_NAME).is_file())

    def test_library_checker_rejects_offline_storage(self):
        from calibre.library.check_library import CheckLibrary

        db = self.open_legacy_api()
        checker = CheckLibrary(str(self.root), db)
        with patch.object(db.backend, 'check_storage', side_effect=OSError(errno.ENOTCONN, 'offline')):
            with self.assertRaises(OSError):
                checker.scan_library((), ())
        self.assertEqual(checker.missing_formats, [])
        self.assertEqual(db.new_api.all_book_ids(), {1})

    def test_export_discovery_includes_separated_and_ordinary_libraries(self):
        from calibre.utils.exim import all_known_libraries

        db = self.open_legacy_api()
        ordinary = self.root.with_name('ordinary')
        ordinary.mkdir()
        (ordinary / 'metadata.db').write_bytes(b'discovery only')
        counts = {str(self.root): 3, str(ordinary): 2}
        with patch('calibre.utils.exim.prefs', {'library_path': str(self.root)}), patch('calibre.gui2.gprefs', {'library_usage_stats': counts}):
            self.assertEqual(all_known_libraries(), counts)
        self.assertEqual(db.dbpath, str(self.local / 'metadata.db'))

    def test_auxiliary_databases_are_local_and_sqlite_integrity_passes(self):
        db = self.open_legacy_api()
        cache = db.new_api
        cache.enable_fts(start_pool=False)
        connection = db.backend.conn
        self.assertEqual(connection.notes_dbpath, str(self.local / '.calnotes' / 'notes.db'))
        self.assertEqual(connection.fts_dbpath, str(self.local / 'full-text-search.db'))
        for schema in ('main', 'notes_db', 'fts_db'):
            with self.subTest(schema=schema):
                self.assertEqual(connection.get(f'PRAGMA {schema}.integrity_check', all=False), 'ok')
                self.assertEqual(connection.get(f'PRAGMA {schema}.foreign_key_check'), [])
        self.assertFalse((self.root / 'metadata.db').exists())
        self.assertFalse((self.root / 'full-text-search.db').exists())
        self.assertFalse((self.root / '.calnotes').exists())

    def test_separated_archive_export_round_trip(self):
        from calibre.db.cache import import_library
        from calibre.db.tests.base import IMG
        from calibre.utils.exim import Exporter, Importer

        db = self.open_legacy_api()
        cache = db.new_api
        cache.set_field('comments', {1: '<p>Exported separated metadata</p>'})
        cache.set_cover({1: IMG})
        author = cache.get_item_id('authors', 'Original author')
        cache.set_notes_for('authors', author, '<p>Exported author note</p>')
        archive, destination = self.root.with_name('archive'), self.root.with_name('imported')
        archive.mkdir()
        destination.mkdir()
        exporter = Exporter(str(archive))
        cache.export_library('phase1', exporter)
        exporter.commit()
        importer = Importer(str(archive))
        self.assertEqual(importer.verify(), [])
        restored = import_library('phase1', importer, str(destination))
        self.addCleanup(restored.close)
        self.assertEqual(restored.format(1, 'TXT'), b'original book')
        self.assertEqual(restored.field_for('comments', 1), '<p>Exported separated metadata</p>')
        self.assertIsNotNone(restored.cover(1))
        author = restored.get_item_id('authors', 'Original author')
        self.assertEqual(restored.notes_for('authors', author), '<p>Exported author note</p>')
        self.assertEqual(restored.dbpath, str(destination / 'metadata.db'))
        self.assertFalse((destination / storage.CONFIG_NAME).exists())
        self.assertTrue((self.root / storage.CONFIG_NAME).exists())

    def test_archive_config_rewrites_current_preferences_and_stale_split_mapping(self):
        from calibre.utils.exim import Exporter, Importer

        self.configure()
        settings, archive, restored = (self.root.with_name(name) for name in ('settings', 'export-config', 'restored-config'))
        for path in (settings, archive, restored):
            path.mkdir()
        other = str(self.root.with_name('unselected-library'))
        records = {str(self.root): self.registry[str(self.root)], other: self.registry[str(self.root)]}
        (settings / 'separated-library-storage.json').write_text(json.dumps(records), encoding='utf-8')
        (settings / 'global.py.json').write_text(json.dumps({'library_path': '/old/source/library', 'language': 'en'}), encoding='utf-8')
        exporter = Exporter(str(archive))
        exporter.export_dir(str(settings), 'config_dir')
        exporter.commit()
        importer = Importer(str(archive))
        importer.export_config(str(restored), Counter({str(self.root): 1}))
        global_prefs = json.loads((restored / 'global.py.json').read_text(encoding='utf-8'))
        self.assertEqual(global_prefs['library_path'], str(self.root))
        self.assertEqual(global_prefs['language'], 'en')
        self.assertEqual(json.loads((restored / 'global.py').read_text(encoding='utf-8'))['library_path'], str(self.root))
        self.assertEqual(json.loads((restored / 'separated-library-storage.json').read_text(encoding='utf-8')), {other: records[other]})

    def test_obsolete_backend_rejects_split_root_before_creating_database(self):
        from calibre.library.database2 import LibraryDatabase2

        self.configure()
        marker = (self.root / storage.CONFIG_NAME).read_bytes()
        with self.assertRaises(ValueError):
            LibraryDatabase2(str(self.root))
        self.assertFalse((self.root / 'metadata.db').exists())
        self.assertEqual((self.root / storage.CONFIG_NAME).read_bytes(), marker)

    def test_obsolete_backend_never_recreates_disconnected_books_root(self):
        from calibre.library.database2 import LibraryDatabase2

        self.configure()
        offline = self.root.with_name('offline-books')
        self.root.rename(offline)
        try:
            with self.assertRaises(OSError):
                LibraryDatabase2(str(self.root))
            self.assertFalse(self.root.exists())
        finally:
            if not self.root.exists():
                offline.rename(self.root)
