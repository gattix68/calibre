#!/usr/bin/env python3
# License: GPLv3
"""Non-mutating Indexed Library creation form with read-only preflight.

Creation and Indexed startup remain disabled until runtime file-operation
guards and integration tests are complete. No ebook source is opened or scanned.
"""
from qt.core import (
    QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout,
)

from calibre.db.indexed_library_creation import validate_indexed_creation
from calibre.utils.localization import _


class IndexedLibraryCreationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Create Indexed Library (experimental)'))
        layout = QVBoxLayout(self)

        description = QLabel(_(
            'Choose an existing empty local directory for the Indexed Library '
            'database and a separate directory for your ebooks. '
            'This preview does not create, scan, move, rename, or delete files.'
        ), self)
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QGridLayout()
        self.database_path = QLineEdit(self)
        self.database_path.setPlaceholderText(_('Existing empty local directory'))
        self.source_path = QLineEdit(self)
        self.source_path.setPlaceholderText(_('Ebook source directory (offline NAS allowed)'))
        for row, (label, field) in enumerate((
            (_('Local database directory:'), self.database_path),
            (_('Ebook source directory:'), self.source_path),
        )):
            form.addWidget(QLabel(label, self), row, 0)
            form.addWidget(field, row, 1)
            browse = QPushButton(_('Browse…'), self)
            browse.clicked.connect(lambda checked=False, target=field: self.browse_directory(target))
            form.addWidget(browse, row, 2)
            field.textChanged.connect(self.validate_paths)
        layout.addLayout(form)

        self.status = QLabel('', self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        self.create_button = buttons.addButton(_('Create Indexed Library'), QDialogButtonBox.ButtonRole.AcceptRole)
        self.create_button.setEnabled(False)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.validate_paths()
        self.resize(750, 230)

    def browse_directory(self, field):
        selected = QFileDialog.getExistingDirectory(
            self, _('Select existing directory'), field.text()
        )
        if selected:
            field.setText(selected)

    def validate_paths(self, *args):
        # This is informational preflight, not permission to create.
        self.create_button.setEnabled(False)
        database = self.database_path.text().strip()
        source = self.source_path.text().strip()
        if not database or not source:
            self.status.setText(_(
                'Select both directories to check their suitability. '
                'Creation remains disabled.'
            ))
            return
        try:
            plan = validate_indexed_creation(database, [source])
        except (OSError, ValueError, RuntimeError) as err:
            self.status.setText(_('Validation failed: %s') % str(err))
        else:
            self.status.setText(_(
                'Paths passed preliminary checks: local database directory is '
                'empty and separate from the ebook source. '
                'Source availability was not checked. '
                'Creation remains disabled pending runtime safety guards.'
            ))
