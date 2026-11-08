#!/usr/bin/env python
# License: GPLv3
"""Outage injection uses disposable libraries only, never a real SMB service."""
import errno
import json
import os
import sqlite3
import unittest
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from calibre.db.separated_storage import CONFIG_NAME, resolve_database_path
from calibre.db.tests import test_separated_storage as shared

ERRORS = (errno.ENOENT, errno.EACCES, errno.EPERM, getattr(errno, 'ESTALE', 116), errno.ENOTCONN, errno.EIO)


class RecoveryTests(unittest.TestCase):
    open_library = shared.SeparatedOperationsTests.open_library
    create_book = shared.SeparatedOperationsTests.create_book

    def setUp(self):
        shared.SeparatedStorageTests.setUp(self)
        from calibre.db.separated_storage import configure_separated_storage
        configure_separated_storage(str(self.root), str(self.local))
        self.cache = self.open_library()
        # Deterministic fault injection, without background scans racing it.
        self.cache.maintain_page_counts.shutdown()
        self.cache.maintain_page_counts.wait_for_worker_shutdown()
        self.cache.maintain_page_counts.queue_scan = lambda *args, **kwargs: None
        self.book = self.create_book(self.cache)
        self.cache.set_field('tags', {self.book: ['Preserved collection']})
        self.cache.set_field('comments', {self.book: '<p>Preserved metadata</p>'})
        self.original = self.state()
        self.source = Path(self.cache.format_abspath(self.book, 'TXT'))

    def state(self):
        with sqlite3.connect((self.local / 'metadata.db').as_uri() + '?mode=ro', uri=True) as conn:
            return {table: conn.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()
                    for table in ('books', 'authors', 'books_authors_link', 'data', 'tags', 'books_tags_link', 'comments')}

    def assert_preserved(self):
        self.assertEqual(self.state(), self.original)
        self.assertEqual(self.cache.field_for('title', self.book), 'Original title')
        self.assertEqual(self.cache.field_for('comments', self.book), '<p>Preserved metadata</p>')
        self.assertEqual(self.source.read_bytes(), b'original book')

    @contextmanager
    def marker_failure(self, code):
        original_open = open
        marker = str(self.root / CONFIG_NAME)

        def failing_open(path, *args, **kwargs):
            if os.fspath(path) == marker:
                raise OSError(code, 'simulated SMB outage', marker)
            return original_open(path, *args, **kwargs)

        with patch('calibre.db.separated_storage.open', side_effect=failing_open):
            yield

    @contextmanager
    def book_path_failure(self, code):
        source = str(self.source.parent)
        filesystem = SimpleNamespace(**vars(os))
        filesystem.path = SimpleNamespace(**vars(os.path))

        def affected(path):
            path = os.fspath(path)
            return path == source or path.startswith(source + os.sep)

        def stat(path, *args, **kwargs):
            if affected(path):
                raise OSError(code, 'simulated inaccessible book directory', path)
            return os.stat(path, *args, **kwargs)

        def exists(path):
            return False if affected(path) else os.path.exists(path)

        def scandir(path):
            if affected(path):
                raise OSError(code, 'simulated stale book directory', path)
            return os.scandir(path)

        filesystem.stat, filesystem.path.exists, filesystem.scandir = stat, exists, scandir
        with patch('calibre.db.backend.os', filesystem):
            yield

    def test_startup_and_operations_reject_smb_errors_then_recover(self):
        from calibre.ebooks.metadata.book.base import Metadata
        from calibre.db.tests.base import IMG
        for code in ERRORS:
            with self.subTest(errno=code), self.marker_failure(code):
                for operation in (
                    lambda: self.open_library(),
                    lambda: self.cache.add_books([(Metadata('Unavailable import', ['Test']), {'TXT': BytesIO(b'new')})], run_hooks=False),
                    lambda: self.cache.add_format(self.book, 'TXT', BytesIO(b'replacement'), run_hooks=False),
                    lambda: self.cache.set_field('title', {self.book: 'Unavailable title'}),
                    lambda: self.cache.set_field('tags', {self.book: ['Unavailable tags']}),
                    lambda: self.cache.set_cover({self.book: IMG}),
                    lambda: self.cache.remove_books({self.book}),
                    lambda: self.cache.remove_books({self.book}, permanent=True),
                    lambda: self.cache.remove_formats({self.book: {'TXT'}}),
                ):
                    with self.assertRaises(OSError):
                        operation()
                self.assert_preserved()
        # No restart is necessary after the same storage identity returns.
        self.assertEqual(self.cache.format(self.book, 'TXT'), b'original book')
        self.cache.set_field('comments', {self.book: '<p>Recovered</p>'})
        self.cache.close()
        reopened = self.open_library()
        self.assertEqual(reopened.field_for('comments', self.book), '<p>Recovered</p>')
        self.assertEqual(reopened.field_for('tags', self.book), ('Preserved collection',))
        self.assertEqual(reopened.format(self.book, 'TXT'), b'original book')
        with sqlite3.connect((self.local / 'metadata.db').as_uri() + '?mode=ro', uri=True) as conn:
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone(), ('ok',))

    def test_initialization_does_not_recreate_marker_after_disconnection(self):
        from calibre.db import separated_storage as storage
        books = self.root.with_name('creating-books')
        local = self.local.with_name('creating-local')
        books.mkdir()
        local.mkdir()
        storage.configure_separated_storage(str(books), str(local))
        config = json.loads((books / CONFIG_NAME).read_text(encoding='utf-8'))
        check = storage.check_storage

        def disappear_after_validation(*args):
            check(*args)
            (books / CONFIG_NAME).unlink()

        with patch('calibre.db.separated_storage.check_storage', side_effect=disappear_after_validation):
            with self.assertRaises(FileNotFoundError):
                storage.mark_initialized(str(books), config)
        self.assertEqual(list(books.iterdir()), [])
        self.assertEqual(self.registry[str(books)], config)

    def test_broken_marker_is_not_an_ordinary_library(self):
        marker = self.root / CONFIG_NAME
        contents = marker.read_bytes()
        marker.unlink()
        try:
            try:
                marker.symlink_to(self.root / 'missing-marker-target')
            except OSError as err:
                self.skipTest(f'Symlinks unavailable: {err}')
            self.registry.clear()
            with self.assertRaises(FileNotFoundError):
                resolve_database_path(str(self.root))
            self.assertFalse((self.root / 'metadata.db').exists())
        finally:
            if marker.is_symlink():
                marker.unlink()
            marker.write_bytes(contents)

    def test_gui_startup_permission_error_is_not_new_library(self):
        from calibre.gui2.main import AbortInit, get_library_path
        errors = []
        runner = SimpleNamespace(show_error=lambda *args, **kwargs: errors.append(args))
        with patch('calibre.gui2.main.prefs', {'library_path': str(self.root)}), self.marker_failure(errno.EACCES):
            with self.assertRaises(AbortInit):
                get_library_path(runner)
        self.assertEqual(len(errors), 1)
        self.registry.clear()
        with patch('calibre.gui2.main.prefs', {'library_path': str(self.root)}), self.marker_failure(errno.EACCES):
            with self.assertRaises(AbortInit):
                get_library_path(runner)
        self.assertEqual(len(errors), 2)
        self.assert_preserved()

    def test_marker_probe_does_not_hide_permission_or_stale_errors(self):
        # A fresh application configuration has no cached identity. lexists()
        # masks filesystem failures; opening the marker must propagate them.
        self.registry.clear()
        filesystem = SimpleNamespace(**vars(os))
        filesystem.path = SimpleNamespace(**vars(os.path))
        filesystem.path.lexists = lambda path: False
        for code in (errno.EACCES, getattr(errno, 'ESTALE', 116), errno.EIO):
            with self.subTest(errno=code), patch('calibre.db.separated_storage.os', filesystem), self.marker_failure(code):
                with self.assertRaises(OSError):
                    resolve_database_path(str(self.root))
        self.assert_preserved()

    def test_delete_never_treats_inaccessible_directory_as_absent(self):
        from calibre.db.errors import BooksNotRemoved
        for code in ERRORS:
            for permanent in (False, True):
                with self.subTest(errno=code, permanent=permanent), self.book_path_failure(code):
                    with self.assertRaises((BooksNotRemoved, OSError)):
                        self.cache.remove_books({self.book}, permanent=permanent)
                self.assert_preserved()
        self.cache.remove_books({self.book})
        self.assertNotIn(self.book, self.cache.all_book_ids())

    def test_title_failure_rolls_back_local_metadata_and_cache(self):
        for code in (errno.EACCES, getattr(errno, 'ESTALE', 116), errno.ENOTCONN):
            with self.subTest(errno=code), patch('calibre.db.backend.copy_tree', side_effect=OSError(code, 'simulated move failure')):
                with self.assertRaises(OSError):
                    self.cache.set_field('title', {self.book: 'Failed title'})
            self.assert_preserved()
        self.cache.set_field('title', {self.book: 'Recovered title'})
        self.assertEqual(self.cache.format(self.book, 'TXT'), b'original book')

    def test_failed_replacement_does_not_truncate_original(self):
        # Existing fallback on a denied staging file truncates the destination
        # before a stream/read failure. Separated storage must fail safely.
        class FailingStream(BytesIO):
            def read(self, *args):
                raise OSError(errno.EIO, 'simulated disconnected stream')

        with patch('calibre.db.backend.tempfile.mkstemp', side_effect=PermissionError(errno.EACCES, 'SMB denied staging')):
            with self.assertRaises(OSError):
                self.cache.add_format(self.book, 'TXT', FailingStream(b'bad'), run_hooks=False)
        self.assert_preserved()
        self.assertTrue(self.cache.add_format(self.book, 'TXT', BytesIO(b'recovered replacement'), run_hooks=False))
        self.assertEqual(self.cache.format(self.book, 'TXT'), b'recovered replacement')

    def test_failed_staged_replacement_preserves_original_and_records(self):
        with patch('calibre.db.backend.prepare_replacement_for', return_value=False):
            with self.assertRaises(OSError):
                self.cache.add_format(self.book, 'TXT', BytesIO(b'unsafe replacement'), run_hooks=False)
        self.assert_preserved()
        with patch('calibre.db.backend.replace_with_retry', side_effect=OSError(errno.EIO, 'replacement failed')):
            with self.assertRaises(OSError):
                self.cache.add_format(self.book, 'TXT', BytesIO(b'incomplete replacement'), run_hooks=False)
        self.assert_preserved()
        self.assertFalse(list(self.root.rglob('.calibre-format-*')))

    def test_failed_author_metadata_update_rolls_back(self):
        from calibre.ebooks.metadata.book.base import Metadata
        with patch('calibre.db.backend.copy_tree', side_effect=OSError(errno.ENOTCONN, 'SMB connection lost')):
            with self.assertRaises(OSError):
                self.cache.set_metadata(self.book, Metadata('New title', ['New author']))
        self.assert_preserved()
        self.assertEqual(self.cache.field_for('authors', self.book), ('Original author',))

    def test_failed_author_move_preserves_author_notes(self):
        author = self.cache.get_item_id('authors', 'Original author')
        self.cache.set_notes_for('authors', author, '<p>Keep author notes</p>')
        with patch('calibre.db.backend.copy_tree', side_effect=OSError(errno.ENOTCONN, 'author move unavailable')):
            with self.assertRaises(OSError):
                self.cache.set_field('authors', {self.book: ['Failed author']})
        self.assertEqual(self.cache.field_for('authors', self.book), ('Original author',))
        self.assertEqual(self.cache.notes_for('authors', author), '<p>Keep author notes</p>')
        self.assertEqual(self.cache.format(self.book, 'TXT'), b'original book')

    def test_rollback_can_reload_cache_while_marker_is_unavailable(self):
        failure = self.marker_failure(errno.ENOTCONN)
        entered = False

        def disconnect(*args, **kwargs):
            nonlocal entered
            failure.__enter__()
            entered = True
            raise OSError(errno.ENOTCONN, 'NAS disappeared during move')

        try:
            with patch('calibre.db.backend.copy_tree', side_effect=disconnect):
                with self.assertRaises(OSError):
                    self.cache.set_field('title', {self.book: 'Must roll back'})
            self.assert_preserved()
            # The bypass is scoped to recovery, not later writes or threads.
            with self.assertRaises(OSError):
                self.cache.set_field('comments', {self.book: 'Must not write'})
        finally:
            if entered:
                failure.__exit__(None, None, None)
        self.assert_preserved()
        self.cache.set_field('tags', {self.book: ['Recovered collection']})

    def test_successful_move_mapping_survives_later_disconnection(self):
        from calibre.db import backend
        original_copy = backend.copy_tree
        failure = self.marker_failure(errno.ENOTCONN)
        entered = False

        def move_then_disconnect(*args, **kwargs):
            nonlocal entered
            original_copy(*args, **kwargs)
            failure.__enter__()
            entered = True

        try:
            with patch('calibre.db.backend.copy_tree', side_effect=move_then_disconnect):
                with self.assertRaises(OSError):
                    self.cache.set_field('title', {self.book: 'Move completed'})
        finally:
            if entered:
                failure.__exit__(None, None, None)
        self.assertEqual(self.cache.field_for('title', self.book), 'Move completed')
        self.assertEqual(self.cache.format(self.book, 'TXT'), b'original book')
        self.cache.close()
        reopened = self.open_library()
        self.assertEqual(reopened.format(self.book, 'TXT'), b'original book')
        self.assertEqual(reopened.field_for('title', self.book), 'Move completed')

    def test_successful_cover_write_retains_its_local_flag(self):
        from calibre.db.tests.base import IMG
        write_cover = self.cache.backend.set_cover
        failure = self.marker_failure(errno.ENOTCONN)
        entered = False

        def write_then_disconnect(*args, **kwargs):
            nonlocal entered
            write_cover(*args, **kwargs)
            failure.__enter__()
            entered = True

        try:
            with patch.object(self.cache.backend, 'set_cover', side_effect=write_then_disconnect):
                self.cache.set_cover({self.book: IMG})
            self.assertTrue(self.cache.field_for('cover', self.book))
        finally:
            if entered:
                failure.__exit__(None, None, None)
        self.assertIsNotNone(self.cache.cover(self.book))
        self.cache.close()
        reopened = self.open_library()
        self.assertTrue(reopened.field_for('cover', self.book))
        self.assertIsNotNone(reopened.cover(self.book))

    def test_partial_bulk_move_keeps_successful_file_mappings(self):
        from calibre.db import backend
        other = self.create_book(self.cache)
        original_copy = backend.copy_tree
        copies = []

        def fail_second(*args, **kwargs):
            copies.append(args[0])
            if len(copies) == 2:
                raise OSError(errno.ENOTCONN, 'second move unavailable')
            return original_copy(*args, **kwargs)

        with patch('calibre.db.backend.copy_tree', side_effect=fail_second):
            with self.assertRaises(OSError):
                self.cache.set_field('title', {self.book: 'First moved title', other: 'Second moved title'})
        self.assertEqual(len(copies), 2)
        self.assertEqual(self.cache.all_book_ids(), {self.book, other})
        for book in (self.book, other):
            self.assertEqual(self.cache.format(book, 'TXT'), b'original book')
        self.cache.close()
        reopened = self.open_library()
        for book in (self.book, other):
            self.assertEqual(reopened.format(book, 'TXT'), b'original book')

    def test_inaccessible_formats_are_not_removed_from_database(self):
        for code in ERRORS:
            with self.subTest(errno=code), self.book_path_failure(code):
                with self.assertRaises(OSError):
                    self.cache.remove_formats({self.book: {'TXT'}})
            self.assert_preserved()
        self.cache.remove_formats({self.book: {'TXT'}})
        self.assertFalse(self.cache.formats(self.book, verify_formats=False))

    def test_background_metadata_backup_retries_after_recovery(self):
        from calibre.db.backup import MetadataBackup
        backup = MetadataBackup(self.cache, interval=0, scheduling_interval=0)
        dirty = self.cache.dirtied_cache.copy()
        self.assertIn(self.book, dirty)
        with self.marker_failure(errno.ENOTCONN), patch('calibre.db.backup.traceback.print_exc'):
            backup.do_one()
        self.assertEqual(self.cache.dirtied_cache, dirty)
        self.assert_preserved()
        backup.do_one()
        self.assertNotIn(self.book, self.cache.dirtied_cache)
        self.assertTrue(list(self.root.rglob('metadata.opf')))

    def test_backup_worker_survives_outage_before_clearing_dirty_flag(self):
        from calibre.db.backup import MetadataBackup
        backup = MetadataBackup(self.cache, interval=0, scheduling_interval=0)
        clear = self.cache.clear_dirtied
        do_one = backup.do_one
        attempts = []

        def clear_after_outage(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError(errno.ENOTCONN, 'outage after OPF write')
            return clear(*args, **kwargs)

        def stop_after_recovery():
            do_one()
            backup.stop()

        with patch.object(self.cache, 'clear_dirtied', side_effect=clear_after_outage), patch.object(backup, 'do_one', side_effect=stop_after_recovery):
            backup.run()
        self.assertEqual(len(attempts), 2)
        self.assertNotIn(self.book, self.cache.dirtied_cache)
        self.assertEqual(self.source.read_bytes(), b'original book')

    def test_background_page_count_does_not_persist_transient_failure(self):
        from calibre.db.page_count import MaintainPageCounts
        counter = MaintainPageCounts(self.cache)
        counter.all_input_formats = {'TXT'}
        counter.sort_order = {'TXT': 0}
        counter.tdir = self.tmp.name
        server = SimpleNamespace(ALGORITHM=1, count_pages=lambda path: 12)
        before = self.cache.get_pages(self.book)
        for code in (errno.EACCES, getattr(errno, 'ESTALE', 116), errno.ENOTCONN):
            with self.subTest(errno=code), self.book_path_failure(code):
                self.assertIsNone(counter.count_book_and_commit(self.book, server))
            self.assertEqual(self.cache.get_pages(self.book), before)
        counter.count_book_and_commit(self.book, server)
        self.assertEqual(self.cache.get_pages(self.book).pages, 12)

    def test_gui_mid_startup_outage_aborts_without_empty_library_fallback(self):
        from calibre.gui2.main import AbortInit, GuiRunner
        errors = []
        runner = SimpleNamespace(
            library_path=str(self.root),
            show_error=lambda *args, **kwargs: errors.append(args),
            initialization_failed=Mock(side_effect=AbortInit),
            initialize_db_stage2=Mock(),
        )
        with patch('calibre.db.legacy.LibraryDatabase', side_effect=OSError(errno.ENOTCONN, 'SMB lost during startup')):
            with self.assertRaises(AbortInit):
                GuiRunner.initialize_db(runner)
        runner.initialize_db_stage2.assert_not_called()
        self.assertEqual(len(errors), 1)
        self.assert_preserved()

    def test_backend_startup_does_not_recreate_storage_lost_after_db_open(self):
        from calibre.db import separated_storage as storage
        self.cache.close()
        offline = self.root.with_name('offline-books')
        complete = storage.mark_initialized

        def lose_storage_after_database_open(*args, **kwargs):
            config = complete(*args, **kwargs)
            self.root.rename(offline)
            return config

        try:
            with patch('calibre.db.separated_storage.mark_initialized', side_effect=lose_storage_after_database_open):
                with self.assertRaises(OSError):
                    self.open_library()
            self.assertFalse(self.root.exists())
        finally:
            offline.rename(self.root)
        reopened = self.open_library()
        self.assertEqual(reopened.field_for('comments', self.book), '<p>Preserved metadata</p>')
        self.assertEqual(reopened.format(self.book, 'TXT'), b'original book')

    def test_cli_startup_does_not_create_empty_mountpoint(self):
        from calibre.gui2.main import AbortInit, init_qt
        offline = self.root.with_name('offline-books')
        self.root.rename(offline)
        try:
            with patch('calibre.gui2.main.find_portable_library'):
                with self.assertRaises(AbortInit):
                    init_qt(['calibre', '--with-library', str(self.root)])
            self.assertFalse(self.root.exists())
        finally:
            offline.rename(self.root)
        self.assert_preserved()

    def test_close_during_outage_then_reopen_retains_books(self):
        with self.marker_failure(errno.EACCES):
            self.cache.close()
        reopened = self.open_library()
        self.assertEqual(reopened.all_book_ids(), {self.book})
        self.assertEqual(reopened.field_for('comments', self.book), '<p>Preserved metadata</p>')
        self.assertEqual(reopened.format(self.book, 'TXT'), b'original book')

    def test_replaced_storage_identity_is_rejected_then_recovers(self):
        marker = self.root / CONFIG_NAME
        original = marker.read_bytes()
        config = json.loads(original)
        config['storage_id'] = 'different-share'
        marker.write_text(json.dumps(config), encoding='utf-8')
        try:
            with self.assertRaises(OSError):
                self.cache.remove_books({self.book})
            with self.assertRaises(OSError):
                self.open_library()
            self.assert_preserved()
        finally:
            marker.write_bytes(original)
        self.assertEqual(self.cache.format(self.book, 'TXT'), b'original book')
