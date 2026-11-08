#!/usr/bin/env python3
# License: GPLv3
"""Discover Calibre's active format-specific metadata handlers.

This module is deliberately read-only. It does not open, inspect, or modify
book files. A registered metadata writer means Calibre has a writer plugin
for the format; it does not guarantee that every Metadata field is supported
by that plugin.
"""

from __future__ import annotations

from typing import Any


def metadata_capabilities(
    fmt: str,
    *,
    readers: Any = None,
    writers: Any = None,
    is_disabled: Any = None,
) -> dict[str, Any]:
    """Return active metadata handlers registered by Calibre for *fmt*.

    Optional arguments make the discovery logic independently testable.
    Normal callers should omit them and use Calibre's initialized plugin
    registry.
    """
    normalized = fmt.lower().strip().lstrip('.')
    if not normalized:
        raise ValueError('A non-empty format is required')

    if readers is None or writers is None or is_disabled is None:
        from calibre.customize.ui import is_disabled as plugin_is_disabled
        from calibre.customize.ui import metadata_readers, metadata_writers

        readers = metadata_readers() if readers is None else readers
        writers = metadata_writers() if writers is None else writers
        is_disabled = plugin_is_disabled if is_disabled is None else is_disabled

    def handlers(plugins: Any) -> list[str]:
        ans = []
        for plugin in plugins:
            file_types = getattr(plugin, 'file_types', ())
            if normalized in {str(x).lower().strip().lstrip('.') for x in file_types}:
                if not is_disabled(plugin):
                    ans.append(str(getattr(plugin, 'name', plugin.__class__.__name__)))
        return sorted(set(ans), key=str.casefold)

    reader_names = handlers(readers)
    writer_names = handlers(writers)
    return {
        'format': normalized.upper(),
        'can_read_metadata': bool(reader_names),
        'can_write_metadata': bool(writer_names),
        'readers': reader_names,
        'writers': writer_names,
    }


def metadata_capabilities_for_formats(
    formats: Any,
    *,
    readers: Any = None,
    writers: Any = None,
    is_disabled: Any = None,
) -> dict[str, dict[str, Any]]:
    """Return metadata-handler availability for a collection of formats."""
    normalized_formats = sorted({str(x).lower().strip().lstrip('.') for x in formats if str(x).strip()})
    if readers is None or writers is None or is_disabled is None:
        from calibre.customize.ui import is_disabled as plugin_is_disabled
        from calibre.customize.ui import metadata_readers, metadata_writers

        readers = metadata_readers() if readers is None else readers
        writers = metadata_writers() if writers is None else writers
        is_disabled = plugin_is_disabled if is_disabled is None else is_disabled
    return {
        fmt.upper(): metadata_capabilities(
            fmt, readers=readers, writers=writers, is_disabled=is_disabled
        )
        for fmt in normalized_formats
    }
