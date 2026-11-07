#!/usr/bin/env python3
# License: GPLv3
"""Non-mutating Indexed Library creation form.

The form collects candidate paths only. It never creates a directory, opens
an Indexed database, or switches the active Managed library. Actual creation
must remain disabled until GUI validation and runtime guards are tested.
"""
from qt.core import (
    QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from calibre.utils.localization import _


class IndexedLibraryCreationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Create Indexed Library (experimental)'))
        layout = QVBoxLayout(self)

        description = QLabel(_(
            'Choose a local directory for the Indexed Library database and '
            'a separate directory containing your existing ebooks. '
            'This preview does not create, scan, move, rename, or delete files.'
        ), self)
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QGridLayout()
        self.database_path = QLineEdit(self)
        self.database_path.setPlaceholderText(_('Existing empty local directory'))
        self.source_path = QLineEdit(self)
        self.source_path.setPlaceholderText(_('Existing ebook source directory (NAS allowed)'))
        for row, (label, field, caption) in enumerate((
            (_('Local database directory:'), self.database_path, _('Browse…')),
            (_('Ebook source directory:'), self.source_path, _('Browse…')),
        )):
            form.addWidget(QLabel(label, self), row, 0)
            form.addWidget(field, row, 1)
            browse = QPushButton(caption, self)
            browse.clicked.connect(lambda checked=False, target=field: self.browse_directory(target))
            form.addWidget(browse, row, 2)
        layout.addLayout(form)

        self.status = QLabel(_(
            'Preview only: creation is disabled until path validation and '
            'runtime file-operation safeguards are integrated and tested.'
        ), self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        self.create_button = buttons.addButton(_('Create Indexed Library'), QDialogButtonBox.ButtonRole.AcceptRole)
        self.create_button.setEnabled(False)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(750, 230)

    def browse_directory(self, field):
        # QFileDialog only selects a path; it does not create an Indexed library.
        selected = QFileDialog.getExistingDirectory(
            self, _('Select existing directory'), field.text()
        )
        if selected:
            field.setText(selected)
