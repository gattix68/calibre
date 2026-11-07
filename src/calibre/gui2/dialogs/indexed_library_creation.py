#!/usr/bin/env python3
# License: GPLv3
"""Isolated Indexed Library creation entry point.

No Managed library callback or automatic library opening is allowed here.
The GUI remains intentionally read-only until its creation workflow has
separate validation and integration tests.
"""
from qt.core import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from calibre.utils.localization import _


class IndexedLibraryCreationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Create Indexed Library (experimental)'))
        layout = QVBoxLayout(self)
        description = QLabel(_(
            'Indexed Library creation is under development. '
            'The existing Managed Library workflow is unchanged. '
            'Indexed libraries cannot be opened until runtime file-operation '
            'guards are implemented and tested.'
        ), self)
        description.setWordWrap(True)
        layout.addWidget(description)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(480, 160)
