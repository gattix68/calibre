#!/usr/bin/env python3
# License: GPLv3
"""Read-only inspection of completed Indexed Libraries.

This dialog never repairs, deletes, opens for writing, or scans ebook sources.
"""
import os

from qt.core import QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout

from calibre.db.indexed_library_config import load_indexed_library_config
from calibre.db.indexed_library_verification import verify_indexed_library_complete
from calibre.utils.localization import _


class IndexedLibraryInspectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Inspect Indexed Library (read-only)'))
        layout = QVBoxLayout(self)
        intro = QLabel(_(
            'Select an Indexed Library directory to perform read-only checks. '
            'Inspection does not repair files or access ebook source contents.'
        ), self)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QGridLayout()
        self.path = QLineEdit(self)
        self.path.setPlaceholderText(_('Indexed Library directory'))
        row.addWidget(self.path, 0, 0)
        browse = QPushButton(_('Browse…'), self)
        browse.clicked.connect(self.browse_directory)
        row.addWidget(browse, 0, 1)
        inspect = QPushButton(_('Inspect'), self)
        inspect.clicked.connect(self.inspect)
        row.addWidget(inspect, 0, 2)
        layout.addLayout(row)

        self.results = QTextEdit(self)
        self.results.setReadOnly(True)
        self.results.setPlaceholderText(_('Inspection results will appear here.'))
        layout.addWidget(self.results)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(720, 420)

    def browse_directory(self):
        selected = QFileDialog.getExistingDirectory(
            self, _('Select Indexed Library directory'), self.path.text()
        )
        if selected:
            self.path.setText(selected)

    def inspect(self):
        library = self.path.text().strip()
        if not library:
            self.results.setPlainText(_('Select a directory first.'))
            return
        try:
            dbpath = verify_indexed_library_complete(library)
            config = load_indexed_library_config(library)
            entries = sorted(os.listdir(library))
        except Exception as err:
            self.results.setPlainText(
                _('Inspection failed; no files were changed.\n\n%s') % str(err)
            )
            return
        lines = [
            _('Result: COMPLETE'),
            _('Database: %s') % dbpath,
            _('SQLite integrity and Indexed schema: passed'),
            _('Configured ebook source roots (paths only; contents not accessed):'),
        ]
        lines.extend('  • ' + root for root in config['source_roots'])
        lines.append(_('Directory entries:'))
        lines.extend('  • ' + name for name in entries)
        lines.append(_('Inspection was read-only. Indexed Library startup remains disabled.'))
        self.results.setPlainText('\n'.join(lines))
