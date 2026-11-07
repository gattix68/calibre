#!/usr/bin/env python3
# License: GPLv3
"""Explicit read-only preview of ebook files in an Indexed Library's sources."""
from qt.core import (
    QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QVBoxLayout,
)

from calibre.db.indexed_file_discovery import discover_ebook_files
from calibre.db.indexed_library_config import load_indexed_library_config
from calibre.db.indexed_library_verification import verify_indexed_library_complete
from calibre.utils.localization import _


class IndexedLibraryDiscoveryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Preview Indexed Source Files (read-only)'))
        layout = QVBoxLayout(self)
        intro = QLabel(_(
            'Inspect a completed Indexed Library and preview ebook files found '
            'under its configured source roots. This operation reads directory '
            'entries and file metadata only; it does not open ebook contents or '
            'change source files or the Indexed database.'
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
        preview = QPushButton(_('Preview files'), self)
        preview.clicked.connect(self.preview)
        row.addWidget(preview, 0, 2)
        layout.addLayout(row)

        self.results = QTextEdit(self)
        self.results.setReadOnly(True)
        self.results.setPlaceholderText(_('Select an Indexed Library and preview its source files.'))
        layout.addWidget(self.results)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(820, 520)

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
            files, errors = discover_ebook_files(config['source_roots'])
        except Exception as err:
            self.results.setPlainText(
                _('Preview failed; no files were changed.\n\n%s') % str(err)
            )
            return

        lines = [
            _('Discovery complete'),
            _('Ebook files found: %d') % len(files),
            _('Source roots: %d') % len(config['source_roots']),
            '',
            _('Discovered files (path, format, size, modified time):'),
        ]
        for item in files:
            lines.append(
                '%s | %s | %d bytes | %d ns'
                % (item['path'], item['format'], item['size'], item['modified_time_ns'])
            )
        lines.extend(('', _('Discovery warnings/errors: %d') % len(errors)))
        for item in errors:
            lines.append('%s: %s' % (item.get('root', item.get('path', '')), item['error']))
        lines.append('')
        lines.append(_('Read-only preview only. No ebook contents or database records were changed.'))
        self.results.setPlainText('\n'.join(lines))
