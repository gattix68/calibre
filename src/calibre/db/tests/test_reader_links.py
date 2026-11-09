#!/usr/bin/env python
# License: GPLv3
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from calibre.db.reader_links import JOURNAL, MANIFEST, Book, Link, LinkManager, Plan, komga_layout, volume_number


class ReaderLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.output = self.root / 'output'
        self.source.mkdir()
        self.output.mkdir()
        self.file = self.source / 'Iron Man.cbz'
        self.file.write_bytes(b'original bytes')
        self.book = Book(1, 'Iron Man', ('Matt Fraction',), 'Iron Man', 1, (('CBZ', str(self.file)),))
        self.manager = LinkManager(str(self.output), 'test-library', (str(self.source),))

    def sync(self, books: list[Book] | None = None) -> Plan:
        plan = self.manager.preview(komga_layout([self.book] if books is None else books))
        self.manager.apply(plan)
        self.assertEqual(self.file.read_bytes(), b'original bytes')
        return plan

    def test_reader_links_lifecycle(self) -> None:
        plan = self.manager.preview(komga_layout([self.book]))
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual([c.kind for c in plan.changes], ['addition'])
        self.sync()
        link = self.output / plan.links[0].path
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.read_bytes(), self.file.read_bytes())
        self.assertEqual(self.sync().changes, [])
        self.assertEqual([c.kind for c in self.sync([self.book, replace(self.book, book_id=2, series_index=2)]).changes], ['addition'])
        self.sync()
        for field in (dict(series='Iron Man: Extremis'), dict(series_index=4), dict(title='Invincible Iron Man')):
            old_path = self.output / komga_layout([self.book])[0].path
            self.book = replace(self.book, **field)
            plan = self.sync()
            self.assertEqual({c.kind for c in plan.changes}, {'relocation', 'removal'})
            self.assertFalse(old_path.exists())
        self.sync([])
        self.assertFalse(any(p.is_symlink() for p in self.output.rglob('*')))

    def test_reader_links_source_relocation_and_broken_link(self) -> None:
        self.sync()
        moved = self.source / 'moved.cbz'
        self.file.rename(moved)
        self.file = moved
        self.book = replace(self.book, formats=(('CBZ', str(moved)),))
        self.assertEqual([c.kind for c in self.sync().changes], ['relocation'])
        link = self.output / komga_layout([self.book])[0].path
        link.unlink()
        self.assertEqual([c.kind for c in self.sync().changes], ['repair'])

    def test_reader_links_missing_source_blocks_removal(self) -> None:
        self.sync()
        before = (self.output / MANIFEST).read_bytes()
        self.file.unlink()
        with self.assertRaises(OSError):
            self.manager.preview(komga_layout([self.book]))
        self.assertEqual((self.output / MANIFEST).read_bytes(), before)

    def test_reader_links_partial_failure_retry_and_changed_desired(self) -> None:
        self.sync()
        before = (self.output / MANIFEST).read_bytes()
        book = replace(self.book, title='Renamed')
        plan = self.manager.preview(komga_layout([book]))
        original = os.symlink

        def fail(source: str, destination: str, *, dir_fd: int | None = None) -> None:
            original(source, destination, dir_fd=dir_fd)
            raise OSError('injected interruption after creating a link')

        with patch('calibre.db.reader_links.os.symlink', side_effect=fail), self.assertRaises(OSError):
            self.manager.apply(plan)
        self.assertEqual((self.output / MANIFEST).read_bytes(), before)
        self.assertTrue((self.output / JOURNAL).exists())
        retry = self.manager.preview(komga_layout([self.book]))
        self.assertTrue(retry.recovering)
        self.manager.apply(retry)
        self.assertFalse((self.output / JOURNAL).exists())
        self.assertFalse(os.path.lexists(self.output / plan.links[0].path))
        self.assertEqual(self.sync().changes, [])

    def test_reader_links_manifest_commit_failure(self) -> None:
        self.sync()
        before = (self.output / MANIFEST).read_bytes()
        plan = self.manager.preview(komga_layout([replace(self.book, title='Changed')]))
        original = os.replace

        def fail(source: str, destination: str, *, src_dir_fd: int | None = None, dst_dir_fd: int | None = None) -> None:
            if destination == MANIFEST:
                raise OSError('manifest commit failed')
            original(source, destination, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

        with patch('calibre.db.reader_links.os.replace', side_effect=fail), self.assertRaises(OSError):
            self.manager.apply(plan)
        self.assertEqual((self.output / MANIFEST).read_bytes(), before)
        self.manager.apply(self.manager.preview(plan.links))
        self.assertEqual(self.manager.preview(plan.links).changes, [])

    def test_reader_links_preserve_foreign_files_and_links(self) -> None:
        links = komga_layout([self.book])
        path = self.output / links[0].path
        path.parent.mkdir()
        path.write_bytes(b'user data')
        with self.assertRaises(OSError):
            self.manager.preview(links)
        self.assertEqual(path.read_bytes(), b'user data')
        path.unlink()
        path.symlink_to(self.file)
        with self.assertRaises(FileExistsError):
            self.manager.preview(links)
        self.assertTrue(path.is_symlink())

    def test_reader_links_external_directory_symlink(self) -> None:
        links = komga_layout([self.book])
        outside = self.root / 'outside'
        outside.mkdir()
        (self.output / links[0].path.split('/')[0]).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.manager.preview(links)
        self.assertEqual(list(outside.iterdir()), [])

    def test_reader_links_changed_owned_link_is_not_deleted(self) -> None:
        self.sync()
        link = self.output / komga_layout([self.book])[0].path
        link.unlink()
        link.symlink_to('/outside/user-data')
        with self.assertRaises(FileExistsError):
            self.manager.preview([])
        self.assertEqual(os.readlink(link), '/outside/user-data')

    def test_reader_links_stale_preview(self) -> None:
        self.sync()
        plan = self.manager.preview([])
        link = self.output / komga_layout([self.book])[0].path
        link.unlink()
        with self.assertRaises(ValueError):
            self.manager.apply(plan)

    def test_reader_links_malformed_state_and_other_library(self) -> None:
        self.sync()
        other = LinkManager(str(self.output), 'other', (str(self.source),))
        with self.assertRaises(ValueError):
            other.preview([])
        state = json.loads((self.output / MANIFEST).read_text())
        state['links'][0]['path'] = '../escape.cbz'
        (self.output / MANIFEST).write_text(json.dumps(state))
        with self.assertRaises(ValueError):
            self.manager.preview([])

    def test_reader_links_source_output_overlap(self) -> None:
        manager = LinkManager(str(self.source), 'test-library', (str(self.source),))
        with self.assertRaises(ValueError):
            manager.preview([])

    def test_reader_links_clean_names_and_numeric_order(self) -> None:
        books = [replace(self.book, book_id=i + 1, series_index=index) for i, index in enumerate((11, 2, 10, 1))]
        links = komga_layout(books)
        self.assertEqual([link.path for link in links], [f'Iron Man/{index:02} - Iron Man.cbz' for index in (1, 2, 10, 11)])
        self.assertEqual([link.book_id for link in links], [4, 2, 3, 1])
        self.assertEqual([link.path for link in links], sorted(link.path for link in links))
        self.sync(books)
        records = json.loads((self.output / MANIFEST).read_text())['links']
        self.assertEqual({r['book_id'] for r in records}, {1, 2, 3, 4})
        self.assertNotIn('[', ''.join(r['path'] for r in records))

    def test_reader_links_fractional_issues_preserve_precision(self) -> None:
        books = [replace(self.book, book_id=i + 1, series_index=index) for i, index in enumerate((1.5, 1.25, 1, 2))]
        links = komga_layout(books)
        self.assertEqual([link.path.split(' - ')[0] for link in links], ['Iron Man/01', 'Iron Man/01.25', 'Iron Man/01.50', 'Iron Man/02'])
        self.assertEqual([link.path for link in links], sorted(link.path for link in links))
        self.assertEqual(volume_number(1.00001), '01.00001')
        self.assertEqual(volume_number(0.0000001), '00.0000001')
        self.assertEqual(volume_number(-1.25), '-01.25')
        self.assertEqual(volume_number(-0.0), '00')
        self.assertEqual(volume_number(1.5, width=1), '1.5')
        self.sync(books)

    def test_reader_links_padding_grows_with_series(self) -> None:
        books = [replace(self.book, book_id=i + 1, series_index=index) for i, index in enumerate((100, 1, 10))]
        self.assertEqual([link.path.split(' - ')[0] for link in komga_layout(books)], ['Iron Man/001', 'Iron Man/010', 'Iron Man/100'])

    def test_reader_links_name_collisions_fail_without_writes(self) -> None:
        for series in (('Iron/Man', 'Iron:Man'), ('Iron Man', 'IRON MAN'), ('A' * 121 + 'one', 'A' * 121 + 'two')):
            with self.subTest(series=series), self.assertRaisesRegex(ValueError, 'collide'):
                self.manager.preview(komga_layout([replace(self.book, series=series[0]), replace(self.book, book_id=2, series=series[1])]))
        with self.assertRaisesRegex(ValueError, 'same link'):
            komga_layout([replace(self.book, title='Iron/Man'), replace(self.book, book_id=2, title='Iron:Man')])
        self.assertEqual(list(self.output.iterdir()), [])
        standalone = replace(self.book, series='')
        self.assertEqual(komga_layout([standalone])[0].path, 'Iron Man/01 - Iron Man.cbz')
        with self.assertRaisesRegex(ValueError, 'collide'):
            komga_layout([standalone, replace(standalone, book_id=2)])

    def test_reader_links_migrate_old_names_by_stable_book_id(self) -> None:
        old = Link(1, 'CBZ', 'Iron Man [0123456789]/0000001.0000 - Iron Man [1].cbz', str(self.file))
        self.manager.apply(self.manager.preview([old]))
        preview = self.manager.preview(komga_layout([self.book]))
        self.assertEqual([change.kind for change in preview.changes], ['relocation', 'removal'])
        self.assertTrue((self.output / old.path).is_symlink())
        self.manager.apply(preview)
        self.assertFalse(os.path.lexists(self.output / old.path))
        self.assertTrue((self.output / 'Iron Man/01 - Iron Man.cbz').is_symlink())
        self.assertEqual(json.loads((self.output / MANIFEST).read_text())['links'][0]['book_id'], 1)
        self.assertEqual(self.file.read_bytes(), b'original bytes')
        self.assertEqual(self.manager.preview(komga_layout([self.book])).changes, [])

    def test_reader_links_symlinked_output_and_missing_output(self) -> None:
        alias = self.root / 'alias'
        alias.symlink_to(self.output, target_is_directory=True)
        for output in (alias, self.root / 'missing'):
            with self.assertRaises(OSError):
                LinkManager(str(output), 'test-library', (str(self.source),)).preview([])

    def test_reader_links_concurrent_writer(self) -> None:
        import fcntl

        from calibre.db.reader_links import LOCK

        with open(self.output / LOCK, 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            plan = self.manager.preview(komga_layout([self.book]))
            with self.assertRaises(BlockingIOError):
                self.manager.apply(plan)
        self.assertFalse((self.output / MANIFEST).exists())
        self.sync()

    def test_reader_links_post_commit_cleanup_warning(self) -> None:
        plan = self.manager.preview(komga_layout([self.book]))
        original = os.unlink

        def fail(path: str, *, dir_fd: int | None = None) -> None:
            if path == JOURNAL:
                raise OSError('cleanup failed after commit')
            original(path, dir_fd=dir_fd)

        with patch('calibre.db.reader_links.os.unlink', side_effect=fail):
            result = self.manager.apply(plan)
        self.assertTrue(result.warnings)
        self.assertTrue((self.output / MANIFEST).exists())
        retry = self.manager.preview(plan.links)
        self.assertTrue(retry.recovering)
        self.manager.apply(retry)
        self.assertFalse((self.output / JOURNAL).exists())

    def test_reader_links_invalid_index_and_source_inside_output(self) -> None:
        with self.assertRaises(ValueError):
            komga_layout([replace(self.book, series_index=float('nan'))])
        source = self.output / 'unowned.cbz'
        source.write_bytes(b'user data')
        with self.assertRaises(ValueError):
            self.manager.preview([Link(1, 'CBZ', 'series/book.cbz', str(source))])
        self.assertEqual(source.read_bytes(), b'user data')


class ReaderLinkDatabaseTests(unittest.TestCase):
    def test_reader_links_real_database_workflow(self) -> None:
        from io import BytesIO

        from calibre.db.backend import DB
        from calibre.db.cache import Cache
        from calibre.db.reader_links import read_books
        from calibre.db.separated_storage import configure_separated_storage
        from calibre.ebooks.metadata.book.base import Metadata

        with tempfile.TemporaryDirectory() as root:
            books, local, output = (Path(root) / x for x in ('books', 'local', 'output'))
            for path in (books, local, output):
                path.mkdir()
            configure_separated_storage(str(books), str(local))
            cache = Cache(DB(str(books)))
            cache.init()
            page_counts = cache.maintain_page_counts
            assert page_counts is not None
            page_counts.shutdown()
            page_counts.wait_for_worker_shutdown()
            queue_scan = patch.object(page_counts, 'queue_scan')
            queue_scan.start()
            try:
                manager = LinkManager(str(output), cache.library_id, (str(books), str(local)))
                mi = Metadata('Iron Man Volume One', ['Matt Fraction'])
                mi.series, mi.series_index = 'Invincible Iron Man', 1
                bid = cache.create_book_entry(mi)
                cache.add_format(bid, 'CBZ', BytesIO(b'comic payload'), run_hooks=False)

                def sync() -> Plan:
                    plan = manager.preview(komga_layout(read_books(cache)))
                    manager.apply(plan)
                    return plan

                self.assertEqual(len(sync().links), 1)
                self.assertEqual(sync().changes, [])
                mi.title, mi.series_index = 'Iron Man Volume Two', 2
                second = cache.create_book_entry(mi)
                cache.add_format(second, 'CBZ', BytesIO(b'volume two'), run_hooks=False)
                self.assertEqual(len(sync().changes), 1)
                for field, value in (('series', 'Iron Man'), ('series_index', 3.5), ('title', 'Renamed Iron Man')):
                    cache.set_field(field, {bid: value})
                    self.assertIn('relocation', {c.kind for c in sync().changes})
                cache.set_field('authors', {bid: ['Different Author']})
                self.assertEqual({c.kind for c in sync().changes}, {'relocation'})
                source_path = cache.format_abspath(bid, 'CBZ')
                assert source_path is not None
                source = Path(source_path)
                self.assertEqual(source.read_bytes(), b'comic payload')
                link = output / next(x.path for x in komga_layout(read_books(cache)) if x.book_id == bid)
                link.unlink()
                self.assertEqual([c.kind for c in sync().changes], ['repair'])
                cache.remove_books({second}, permanent=True)
                self.assertEqual([c.kind for c in sync().changes], ['removal'])
                before = (output / MANIFEST).read_bytes()
                with patch.object(cache.backend, 'check_storage', side_effect=OSError('storage missing')):
                    with self.assertRaises(OSError):
                        read_books(cache)
                self.assertEqual((output / MANIFEST).read_bytes(), before)
                self.assertEqual(sync().changes, [])
            finally:
                queue_scan.stop()
                cache.close()
