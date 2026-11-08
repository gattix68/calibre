#!/usr/bin/env python3
# License: GPLv3
"""Build a reviewable registration plan from read-only Indexed source discovery.

This module does not write the database or modify source files.
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Any


def _metadata_value(metadata: Any, field: str) -> Any:
    if metadata is None:
        return None
    if isinstance(metadata, dict):
        return metadata.get(field)
    value = getattr(metadata, field, None)
    if value is None and callable(getattr(metadata, 'get', None)):
        try:
            value = metadata.get(field)
        except Exception:
            pass
    return value


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, bytes)):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _normal_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().casefold()
    if isinstance(value, (list, tuple)):
        return tuple(_normal_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(k).casefold(), _normal_value(v)) for k, v in value.items()))
    return value


def build_indexed_registration_plan(scan_result: dict[str, Any]) -> dict[str, Any]:
    """Group same-folder, same-basename formats into proposed Calibre books.

    Grouping is intentionally conservative: only files with the same
    case-insensitive filename stem in the same directory are grouped.
    Metadata is not silently merged. The first readable metadata record is
    selected as a proposal and disagreements are surfaced for review.
    """
    if not isinstance(scan_result, dict) or not isinstance(scan_result.get('files'), list):
        raise ValueError('Scan result must contain a files list')

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    invalid: list[dict[str, Any]] = []
    for item in scan_result['files']:
        if not isinstance(item, dict):
            invalid.append({'item': repr(item), 'reason': 'not a file record'})
            continue
        file_path = item.get('file_path')
        fmt = str(item.get('format') or '').strip().upper().lstrip('.')
        if not isinstance(file_path, str) or not os.path.isabs(file_path) or not fmt:
            invalid.append({'file_path': file_path, 'reason': 'missing absolute path or format'})
            continue
        parent = os.path.normcase(os.path.abspath(os.path.dirname(file_path)))
        stem = os.path.splitext(os.path.basename(file_path))[0].casefold()
        groups[(parent, stem)].append(item)

    books: list[dict[str, Any]] = []
    for (parent, stem), records in sorted(groups.items()):
        records.sort(key=lambda item: (str(item['format']).upper(), item['file_path'].casefold()))
        by_format: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            by_format[str(record['format']).upper()].append(record)

        duplicate_formats = {
            fmt: [record['file_path'] for record in same_format]
            for fmt, same_format in by_format.items() if len(same_format) > 1
        }
        metadata_sources = [
            record for record in records
            if record.get('metadata') is not None and not record.get('error')
        ]
        selected = metadata_sources[0] if metadata_sources else None
        fields = ('title', 'authors', 'publisher', 'series', 'series_index',
                  'pubdate', 'comments', 'tags', 'identifiers', 'languages')
        proposed_metadata = {}
        conflicts = {}
        if selected is not None:
            for field in fields:
                selected_value = _metadata_value(selected['metadata'], field)
                if _present(selected_value):
                    proposed_metadata[field] = selected_value
                values = []
                for record in metadata_sources:
                    value = _metadata_value(record['metadata'], field)
                    if _present(value):
                        values.append((record['file_path'], value))
                distinct = {}
                for file_path, value in values:
                    distinct.setdefault(repr(_normal_value(value)), []).append(file_path)
                if len(distinct) > 1:
                    conflicts[field] = [
                        {'file_paths': paths, 'value': value}
                        for value, paths in (
                            (key, [p for p, v in values if repr(_normal_value(v)) == key])
                            for key in distinct
                        )
                    ]

        books.append({
            'group_key': {'directory': parent, 'filename_stem': stem},
            'formats': [
                {
                    'format': fmt,
                    'file_path': same_format[0]['file_path'],
                    'file_size': same_format[0].get('file_size'),
                    'modified_time_ns': same_format[0].get('modified_time_ns'),
                }
                for fmt, same_format in sorted(by_format.items())
                if len(same_format) == 1
            ],
            'duplicate_formats': duplicate_formats,
            'metadata_source': selected.get('file_path') if selected else None,
            'proposed_metadata': proposed_metadata,
            'metadata_conflicts': conflicts,
            'requires_review': bool(duplicate_formats or conflicts or not proposed_metadata),
        })

    books.sort(key=lambda item: (
        item['group_key']['directory'].casefold(),
        item['group_key']['filename_stem'],
    ))
    return {
        'books': books,
        'invalid_records': invalid,
        'scan_errors': list(scan_result.get('errors', ())),
        'skipped_files': list(scan_result.get('skipped', ())),
        'book_count': len(books),
        'file_count': sum(len(book['formats']) + sum(
            len(paths) for paths in book['duplicate_formats'].values()
        ) for book in books),
        'review_count': sum(book['requires_review'] for book in books),
    }
