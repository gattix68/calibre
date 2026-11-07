#!/usr/bin/env python3
# License: GPLv3
"""Read-only metadata extraction preview for Indexed Library source files."""
from qt.core import (
    QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QVBoxLayout,
)

from calibre.db.indexed_file_discovery import discover_ebook_files
from calibre.db.indexed_library_config import load_indexed_library_config
from calibre.db.indexed_library_verification import verify_indexed_library_complete
from calibre.db.indexed_metadata_extraction import extract_metadata_read_only
from calibre.utils.localization import _


class IndexedLibraryMetadataDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Preview Indexed Ebook Metadata (read-only)'))
        layout = QVBoxLayout(self)
        intro = QLabel(_(
            'Extract metadata from discovered ebooks in disposable worker processes. '
            'This preview does not write metadata, covers, database records, or source files.'
        ), self)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QGridLayout()
        self.library_path = QLineEdit(self)
        self.library_path.setPlaceholderText(_('Indexed Library directory'))
        row.addWidget(self.library_path, 0, 0)
        browse = QPushButton(_('Browse…'), self)
        browse.clicked.connect(self.browse_directory)
        row.addWidget(browse, 0, 1)
        preview = QPushButton(_('Extract metadata'), self)
        preview.clicked.connect(self.preview)
        row.addWidget(preview, 0, 2)
        layout.addLayout(row)

        self.results = QTextEdit(self)
        self.results.setReadOnly(True)
        self.results.setPlaceholderText(_('Metadata preview results will appear here.'))
        layout.addWidget(self.results)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(850, 600)

    def browse_directory(self):
        selected = QFileDialog.getExistingDirectory(
            self, _('Select Indexed Library directory'), self.library_path.text()
        )
        if selected:
            self.library_path.setText(selected)

    def preview(self):
        library = self.library_path.text().strip()
        if not library:
            self.results.setPlainText(_('Select an Indexed Library directory first.'))
            return
        try:
            verify_indexed_library_complete(library)
            config = load_indexed_library_config(library)
            files, scan_errors = discover_ebook_files(config['source_roots'])
        except Exception as err:
            self.results.setPlainText(_('Preview failed; no files were changed.\n\n%s') % str(err))
            return

        lines = [_('Files discovered: %d') % len(files), '']
        failures = []
        for item in files:
            lines.append('=' * 72)
            lines.append(item['path'])
            try:
                mi = extract_metadata_read_only(item['path'])
            except Exception as err:
                failures.append((item['path'], str(err)))
                lines.append(_('Metadata extraction failed: %s') % str(err))
                continue
            lines.extend((
                _('Title: %s') % (mi.get('title') or _('Unknown')),
                _('Authors: %s') % (', '.join(mi.get('authors') or []) or _('Unknown')),
                _('Series: %s') % (mi.get('series') or _('—')),
                _('Series index: %s') % (mi.get('series_index') or _('—')),
                _('Publisher: %s') % (mi.get('publisher') or _('—')),
                _('Publication date: %s') % (mi.get('publication_date') or _('—')),
                _('Identifiers: %s') % (', '.join(f'{k}: {v}' for k, v in mi.get('identifiers', {}).items()) or _('—')),
                _('Languages: %s') % (', '.join(mi.get('languages') or []) or _('—')),
                _('Tags: %s') % (', '.join(mi.get('tags') or []) or _('—')),
                _('Cover available: %s') % (_('Yes') if mi.get('has_cover') else _('No')),
            ))

        lines.extend(('', _('Discovery warnings/errors: %d') % len(scan_errors)))
        for item in scan_errors:
            lines.append('%s: %s' % (item.get('root', item.get('path', '')), item['error']))
        lines.extend(('', _('Metadata extraction failures: %d') % len(failures)))
        for path, error in failures:
            lines.append('%s: %s' % (path, error))
        lines.extend(('', _('Read-only preview. No source files or Indexed Library database records were changed.')))
        self.results.setPlainText('\n'.join(lines))
