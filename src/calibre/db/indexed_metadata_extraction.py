#!/usr/bin/env python3
# License: GPLv3
"""Read-only ebook metadata extraction for Indexed Library preview.

Each file is parsed in a disposable Calibre worker process. No import plugins,
metadata writers, cover writers, or database operations are invoked.
"""
import os
import re
import zipfile
from datetime import date, datetime
from xml.etree import ElementTree


MAX_COMICINFO_BYTES = 2 * 1024 * 1024


def _plain(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None:
        return ''
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _comicinfo_bytes(path, ext):
    """Read only ComicInfo.xml from CBZ/CBR without extracting archive paths."""
    member = None
    if ext == 'cbz':
        with zipfile.ZipFile(path) as archive:
            matches = [n for n in archive.namelist() if n.replace('\\\\', '/').casefold().rsplit('/', 1)[-1] == 'comicinfo.xml']
            if matches:
                info = archive.getinfo(matches[0])
                if info.file_size > MAX_COMICINFO_BYTES:
                    raise ValueError('ComicInfo.xml exceeds the 2 MiB safety limit')
                member = archive.read(info)
    elif ext == 'cbr':
        from calibre.utils.unrar import extract_member
        member = extract_member(path, match=re.compile(r'(^|/)ComicInfo\\.xml$', re.I))
        if member is not None:
            member = member[1]
            if len(member) > MAX_COMICINFO_BYTES:
                raise ValueError('ComicInfo.xml exceeds the 2 MiB safety limit')
    return member


def _comicinfo_metadata(path, ext):
    """Return ComicInfo.xml values and field-level provenance, if present."""
    raw = _comicinfo_bytes(path, ext)
    if raw is None:
        return {}, {}
    if len(raw) > MAX_COMICINFO_BYTES:
        raise ValueError('ComicInfo.xml exceeds the 2 MiB safety limit')
    root = ElementTree.fromstring(raw)
    values = {child.tag.rsplit('}', 1)[-1].casefold(): (child.text or '').strip() for child in root}
    result, sources = {}, {}

    def put(field, value):
        if value not in (None, '', [], {}):
            result[field] = value
            sources[field] = 'ComicInfo.xml'

    put('title', values.get('title'))
    put('series', values.get('series'))
    number = values.get('number')
    if number:
        try:
            put('series_index', float(number))
        except ValueError:
            pass
    writers = [x.strip() for x in re.split(r'[,;]', values.get('writer', '')) if x.strip()]
    put('authors', writers)
    put('publisher', values.get('publisher'))
    put('comments', values.get('summary'))
    genres = [x.strip() for x in re.split(r'[,;]', values.get('genre', '')) if x.strip()]
    put('tags', genres)
    language = values.get('languageiso')
    put('languages', [language] if language else None)

    year, month, day = (values.get(k) for k in ('year', 'month', 'day'))
    if year and year.isdigit():
        try:
            y = int(year)
            m = int(month) if month and month.isdigit() else 1
            d = int(day) if day and day.isdigit() else 1
            put('publication_date', date(y, m, d).isoformat())
        except ValueError:
            pass
    return result, sources


def extract_metadata_worker(path):
    """Worker entry point: parse one ebook and return only plain metadata."""
    from calibre.ebooks.metadata.meta import get_metadata

    ext = os.path.splitext(path)[1][1:].lower()
    with open(path, 'rb') as stream:
        mi = get_metadata(stream, stream_type=ext, use_libprs_metadata=False, force_read_metadata=True)

    result = {
        'path': path,
        'format': ext,
        'title': _plain(mi.title),
        'authors': [_plain(x) for x in (mi.authors or [])],
        'series': _plain(mi.series),
        'series_index': _plain(mi.series_index),
        'publisher': _plain(mi.publisher),
        'publication_date': _plain(mi.pubdate),
        'comments': _plain(getattr(mi, 'comments', '')),
        'identifiers': {str(k): str(v) for k, v in (mi.identifiers or {}).items()},
        'languages': [_plain(x) for x in (mi.languages or [])],
        'tags': [_plain(x) for x in (mi.tags or [])],
        'has_cover': bool(mi.cover_data and mi.cover_data[-1]),
        'metadata_sources': {},
    }
    # Filename/file-reader metadata is the fallback. ComicInfo.xml is
    # authoritative for any fields it actually supplies.
    comic_values, comic_sources = _comicinfo_metadata(path, ext) if ext in {'cbz', 'cbr'} else ({}, {})
    result.update(comic_values)
    result['metadata_sources'].update(comic_sources)
    for field in result:
        if field not in {'path', 'format', 'metadata_sources'} and field not in comic_sources:
            result['metadata_sources'].setdefault(field, 'Calibre file reader or filename fallback')
    return result


def extract_metadata_read_only(path, *, timeout=120):
    """Extract metadata in a worker with a hard timeout; never write to source."""
    from calibre.utils.ipc.simple_worker import fork_job

    if not os.path.isabs(path):
        raise ValueError('Ebook path must be absolute')
    if os.path.islink(path) or not os.path.isfile(path):
        raise ValueError('Ebook must be a regular, non-symbolic-link file')
    result = fork_job(
        'calibre.db.indexed_metadata_extraction', 'extract_metadata_worker',
        args=(path,), timeout=timeout, priority='low', no_output=False,
    )
    return result['result']
