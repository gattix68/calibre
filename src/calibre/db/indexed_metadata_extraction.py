#!/usr/bin/env python3
# License: GPLv3
"""Read-only ebook metadata extraction for Indexed Library preview.

Each file is parsed in a disposable Calibre worker process. No import plugins,
metadata writers, cover writers, or database operations are invoked.
"""
import os
from datetime import date, datetime


def _plain(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None:
        return ''
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def extract_metadata_worker(path):
    """Worker entry point: parse one ebook and return only plain metadata."""
    from calibre.ebooks.metadata.meta import get_metadata

    ext = os.path.splitext(path)[1][1:].lower()
    with open(path, 'rb') as stream:
        mi = get_metadata(stream, stream_type=ext, use_libprs_metadata=False, force_read_metadata=True)

    return {
        'path': path,
        'format': ext,
        'title': _plain(mi.title),
        'authors': [_plain(x) for x in (mi.authors or [])],
        'series': _plain(mi.series),
        'series_index': _plain(mi.series_index),
        'publisher': _plain(mi.publisher),
        'publication_date': _plain(mi.pubdate),
        'identifiers': {str(k): str(v) for k, v in (mi.identifiers or {}).items()},
        'languages': [_plain(x) for x in (mi.languages or [])],
        'tags': [_plain(x) for x in (mi.tags or [])],
        'has_cover': bool(mi.cover_data and mi.cover_data[-1]),
    }


def extract_metadata_read_only(path, *, timeout=120):
    """Extract metadata in a worker with a hard timeout; never write to source."""
    from calibre.utils.ipc.simple_worker import WorkerError, fork_job

    if not os.path.isabs(path):
        raise ValueError('Ebook path must be absolute')
    if os.path.islink(path) or not os.path.isfile(path):
        raise ValueError('Ebook must be a regular, non-symbolic-link file')
    result = fork_job(
        'calibre.db.indexed_metadata_extraction', 'extract_metadata_worker',
        args=(path,), timeout=timeout, priority='low', no_output=False,
    )
    return result['result']
