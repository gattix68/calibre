#!/usr/bin/env python
# License: GPLv3
"""User-initiated reader views. Sources are read only; state lives in the output.

Linux prototype: descriptor-relative IO and O_NOFOLLOW keep cleanup confined.
A write-ahead ownership journal makes partial runs retryable without publishing
an unsuccessful manifest. Empty output directories are deliberately retained.
"""

import hashlib
import json
import math
import os
import re
import stat
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

    from calibre.db.cache import Cache

MANIFEST = '.calibre-komga-manifest.json'
JOURNAL = '.calibre-komga-pending.json'
LOCK = '.calibre-komga-lock'
FORMATS = frozenset(('CBZ', 'CBR', 'PDF', 'EPUB'))


@dataclass(frozen=True)
class Book:
    book_id: int
    title: str
    authors: tuple[str, ...]
    series: str
    series_index: float
    formats: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Link:
    book_id: int
    fmt: str
    path: str
    target: str


@dataclass(frozen=True)
class Change:
    kind: str
    path: str
    target: str


@dataclass
class Plan:
    links: list[Link]
    changes: list[Change]
    state: str
    recovering: bool
    warnings: list[str] = field(default_factory=list)


def read_books(db: Cache) -> list[Book]:
    # Hold one Calibre read lock for a consistent metadata/path snapshot.
    db.backend.check_storage()
    os.stat(db.backend.library_path)
    with db.safe_read_lock:
        books = []
        for bid in sorted(db.all_book_ids()):
            formats = []
            for fmt in db.formats(bid, verify_formats=False):
                if fmt in FORMATS:
                    path = db.format_abspath(bid, fmt)
                    if not path or not os.path.isfile(path):
                        raise OSError(f'Book {bid}: unavailable {fmt} source: {path}')
                    formats.append((fmt, os.path.abspath(path)))
            index = db.field_for('series_index', bid)
            if index is not None and not isinstance(index, (int, float)):
                raise ValueError(f'Book {bid}: invalid series index: {index!r}')
            books.append(
                Book(
                    bid,
                    db.field_for('title', bid) or 'Unknown',
                    tuple(db.field_for('authors', bid)),
                    db.field_for('series', bid) or '',
                    float(index or 0),
                    tuple(formats),
                )
            )
        return books


def component(value: str) -> str:
    value = re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', value).strip(' .') or 'Unknown'
    return value.encode('utf-8')[:120].decode('utf-8', errors='ignore')


def volume_number(index: float, width: int = 2, precision: int = 0) -> str:
    """Readable decimal notation; equal fractional widths sort numerically too."""
    if not math.isfinite(index):
        raise ValueError(f'Invalid series index: {index!r}')
    value = Decimal(str(index))
    whole, separator, fraction = format(abs(value), 'f').partition('.')
    fraction = fraction.rstrip('0')
    number = whole.zfill(width)
    if fraction:
        number += '.' + fraction.ljust(precision, '0')
    return ('-' if value < 0 else '') + number


def komga_layout(books: list[Book]) -> list[Link]:
    # Group strictly by the Series field. A book without a series gets its own
    # title folder; ambiguous sanitized/case-folded names fail before writes.
    groups = {}
    folders = {}
    for book in books:
        if not book.formats:
            continue
        if not math.isfinite(book.series_index):
            raise ValueError(f'Invalid series index for book {book.book_id}')
        identity = ('series', book.series) if book.series else ('book', str(book.book_id))
        label = book.series or book.title
        folder = component(label)
        key = unicodedata.normalize('NFC', folder).casefold()
        if key in folders and folders[key] != identity:
            raise ValueError(f'Series or standalone titles collide in output folder {folder!r}. Give them distinct names in Calibre metadata.')
        folders[key] = identity
        groups.setdefault(identity, []).append((folder, book))
    result = []
    used = {}
    for group in sorted(groups.values(), key=lambda g: g[0][0].casefold()):
        parts = [format(abs(Decimal(str(book.series_index))), 'f').partition('.') for folder, book in group]
        width = max(2, *(len(whole) for whole, separator, fraction in parts))
        precision = max(len(fraction.rstrip('0')) for whole, separator, fraction in parts)
        for folder, book in sorted(group, key=lambda entry: (entry[1].series_index, entry[1].title.casefold(), entry[1].book_id)):
            number = volume_number(book.series_index, width, precision)
            for fmt, target in book.formats:
                filename = f'{number} - {component(book.title)}.{fmt.lower()}'
                path = folder + '/' + filename
                key = unicodedata.normalize('NFC', path).casefold()
                if key in used:
                    raise ValueError(f'Books {used[key]} and {book.book_id} produce the same link {path!r}. Give them distinct titles or series indexes.')
                used[key] = book.book_id
                result.append(Link(book.book_id, fmt, path, target))
    return result


def validate_link(link: Link) -> None:
    parts = link.path.split('/')
    if len(parts) != 2 or any(p in ('', '.', '..') or '\\' in p or '\x00' in p for p in parts):
        raise ValueError('Invalid owned link path')
    if type(link.book_id) is not int or link.book_id <= 0 or link.fmt not in FORMATS or not os.path.isabs(link.target):
        raise ValueError('Invalid owned link record')


class LinkManager:
    def __init__(self, output: str, library_id: str, source_roots: tuple[str, ...]) -> None:
        self.output = os.path.abspath(output)
        self.library_id = library_id
        self.source_roots = source_roots

    @contextmanager
    def root(self) -> Generator[int]:
        if os.name != 'posix' or not hasattr(os, 'O_NOFOLLOW'):
            raise OSError('The safe link prototype currently requires POSIX descriptor-relative IO')
        from calibre.db.separated_storage import validate_directories

        for source in self.source_roots:
            validate_directories(self.output, source)
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in self.output.split('/')[1:]:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
            yield fd
        finally:
            os.close(fd)

    def load(self, fd: int, name: str) -> list[Link] | None:
        try:
            streamfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return None
        with os.fdopen(streamfd, encoding='utf-8') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('Synchronization state must be a regular file')
            data = json.load(stream)
        if type(data['version']) is not int or data['version'] != 1 or data['library_id'] != self.library_id or data['output'] != self.output:
            raise ValueError('Output belongs to another library or has invalid state')
        links = [Link(**record) for record in data['links']]
        for link in links:
            validate_link(link)
        return links

    def save(self, fd: int, name: str, links: list[Link]) -> list[str]:
        temp = '.calibre-komga-' + uuid.uuid4().hex
        published = False
        try:
            streamfd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            with os.fdopen(streamfd, 'w', encoding='utf-8') as stream:
                json.dump(dict(version=1, library_id=self.library_id, output=self.output, links=[asdict(link) for link in links]), stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
            published = True
            try:
                os.fsync(fd)
            except OSError as err:
                if name != MANIFEST:
                    raise
                # Publication already committed. Report durability uncertainty as
                # a warning rather than misreporting a rolled-back transaction.
                return [f'Manifest committed, but directory flush failed: {err}']
            return []
        finally:
            if not published:
                try:
                    os.unlink(temp, dir_fd=fd)
                except FileNotFoundError:
                    pass

    @contextmanager
    def parent(self, fd: int, path: str, create: bool = False) -> Generator[tuple[int, str]]:
        folder, name = path.split('/')
        if create:
            try:
                os.mkdir(folder, dir_fd=fd)
                os.fsync(fd)
            except FileExistsError:
                pass
        child = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            yield child, name
        finally:
            os.close(child)

    def target(self, fd: int, path: str) -> str | None:
        try:
            with self.parent(fd, path) as (child, name):
                try:
                    return os.readlink(name, dir_fd=child)
                except FileNotFoundError:
                    return None
        except FileNotFoundError:
            return None

    def plan_at(self, fd: int, links: list[Link]) -> Plan:
        old = self.load(fd, MANIFEST) or []
        journal = self.load(fd, JOURNAL)
        owned = old + (journal or [])
        allowed = {}
        for link in owned:
            allowed.setdefault(link.path, set()).add(link.target)
        desired = {link.path: link for link in links}
        if len(desired) != len(links):
            raise ValueError('Output filename collision')
        previous = {(link.book_id, link.fmt): link for link in old}
        changes = []
        for link in links:
            validate_link(link)
            if not os.path.isfile(link.target):
                raise OSError(f'Unavailable source: {link.target}')
            if os.path.commonpath((self.output, os.path.realpath(link.target))) == self.output:
                raise ValueError('A source cannot be inside the output directory')
            actual = self.target(fd, link.path)
            if actual is not None and (link.path not in allowed or actual not in allowed[link.path]):
                raise FileExistsError(f'Unowned or externally changed link: {link.path}')
            prev = previous.get((link.book_id, link.fmt))
            if actual != link.target:
                kind = 'addition' if prev is None else 'relocation' if (prev.path, prev.target) != (link.path, link.target) else 'repair'
                changes.append(Change(kind, link.path, link.target))
        for path, targets in allowed.items():
            if path not in desired:
                actual = self.target(fd, path)
                if actual is not None:
                    if actual not in targets:
                        raise FileExistsError(f'Owned link was changed externally: {path}')
                    changes.append(Change('removal', path, actual))
        token = hashlib.sha256(
            json.dumps(
                [asdict(x) for x in links] + [asdict(x) for x in old] + [asdict(x) for x in (journal or [])] + [asdict(x) for x in changes], sort_keys=True
            ).encode()
        ).hexdigest()
        return Plan(links, changes, token, journal is not None)

    def preview(self, links: list[Link]) -> Plan:
        with self.root() as fd:
            return self.plan_at(fd, links)

    def apply(self, preview: Plan) -> Plan:
        import fcntl

        with self.root() as fd:
            lockfd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=fd)
            try:
                if not stat.S_ISREG(os.fstat(lockfd).st_mode):
                    raise ValueError('Invalid synchronization lock')
                fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                current = self.plan_at(fd, preview.links)
                if current.state != preview.state:
                    raise ValueError('Output changed after preview. Preview again before applying.')
                owned = (self.load(fd, MANIFEST) or []) + (self.load(fd, JOURNAL) or [])
                self.save(fd, JOURNAL, owned + current.links)
                for change in current.changes:
                    with self.parent(fd, change.path, create=change.kind != 'removal') as (child, name):
                        # Recheck ownership immediately before unlinking. Never overwrite a regular file.
                        actual = self.target(fd, change.path)
                        permitted = {x.target for x in owned if x.path == change.path}
                        if actual is not None:
                            if actual not in permitted:
                                raise FileExistsError(f'Link changed during sync: {change.path}')
                            os.unlink(name, dir_fd=child)
                        if change.kind != 'removal':
                            os.symlink(change.target, name, dir_fd=child)
                        os.fsync(child)
                for link in current.links:
                    if self.target(fd, link.path) != link.target or not os.path.isfile(link.target):
                        raise OSError(f'Link verification failed: {link.path}')
                current.warnings.extend(self.save(fd, MANIFEST, current.links))
                try:
                    os.unlink(JOURNAL, dir_fd=fd)
                    os.fsync(fd)
                except OSError as err:
                    current.warnings.append(f'Synchronization committed; recovery-journal cleanup failed: {err}')
                return current
            finally:
                os.close(lockfd)
