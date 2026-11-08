#!/usr/bin/env python
# License: GPLv3
"""Dedicated toolbar action for Indexed Library operations."""

import os

from qt.core import QToolButton

from calibre.gui2.actions import InterfaceAction
from calibre.utils.localization import _


class IndexedLibraryAction(InterfaceAction):
    name = 'Indexed Library'
    action_spec = (
        _('Indexed Library'), 'indexed-library.svg',
        _('Create and manage an Indexed Library'), None,
    )
    action_add_menu = True
    popup_type = QToolButton.ToolButtonPopupMode.InstantPopup
    dont_add_to = frozenset(('context-menu-device', 'menubar-device'))

    def genesis(self):
        self.menu = self.qaction.menu()
        self.menu.aboutToShow.connect(self.populate_menu)
        self.create_action(
            spec=(_('Create Indexed Library'), 'indexed-library.svg', None, None),
            attr='create_indexed_action',
        ).triggered.connect(self.create_indexed_library)
        self.create_action(
            spec=(_('Inspect Current Indexed Library'), 'view.png', None, None),
            attr='inspect_indexed_action',
        ).triggered.connect(self.inspect_indexed_library)
        self.create_action(
            spec=(_('Sync Library'), 'refresh.png', None, None),
            attr='sync_indexed_action',
        ).triggered.connect(self.sync_indexed_library)
        self.update_library_identity()

    def library_changed(self, db):
        self.update_library_identity()

    def update_library_identity(self):
        from calibre.db.indexed_library_config import load_indexed_library_config

        db = getattr(self.gui, 'current_db', None)
        path = getattr(db, 'library_path', '') if db is not None else ''
        try:
            config = load_indexed_library_config(path) if path else None
        except Exception:
            config = None
        self.is_indexed = config is not None
        self.indexed_name = os.path.basename(os.path.abspath(path)) if self.is_indexed else ''
        label = _('Indexed Library') + (f'\n{self.indexed_name}' if self.is_indexed else '')
        self.qaction.setText(label)
        self.menuless_qaction.setText(label)
        self.qaction.setToolTip(
            _('Currently loaded Indexed Library: %s') % self.indexed_name
            if self.is_indexed else _('No Indexed Library is currently loaded')
        )

    def populate_menu(self):
        self.menu.clear()
        self.menu.addAction(self.create_indexed_action)
        self.menu.addSeparator()
        inspect = self.menu.addAction(self.inspect_indexed_action)
        inspect.setEnabled(self.is_indexed)
        sync = self.menu.addAction(self.sync_indexed_action)
        sync.setEnabled(self.is_indexed)
        sync.setToolTip(_('Scan configured source folders and reconcile renamed files'))

    def create_indexed_library(self):
        from calibre.gui2.dialogs.indexed_library_creation import IndexedLibraryCreationDialog

        IndexedLibraryCreationDialog(self.gui).exec()

    def inspect_indexed_library(self):
        from calibre.gui2.dialogs.indexed_library_inspection import IndexedLibraryInspectionDialog

        IndexedLibraryInspectionDialog(self.gui).exec()

    def sync_indexed_library(self):
        if not self.is_indexed:
            return
        from calibre.gui2 import error_dialog, info_dialog

        try:
            db = self.gui.current_db
            result = db.new_api.sync_indexed_library_files()
            db.commit()
            self.update_library_identity()
            try:
                self.gui.library_view.model().refresh()
            except Exception:
                pass
        except Exception as err:
            error_dialog(
                self.gui, _('Indexed Library synchronization failed'),
                str(err), show=True,
            )
            return

        renamed = result['renamed_count']
        ambiguous = result['ambiguous_count']
        unmatched = result['unmatched_count']
        details = _(
            'Indexed Library scan complete.\\n\\n'
            'Renamed files reconciled: {renamed}\\n'
            'Ambiguous matches (left unchanged): {ambiguous}\\n'
            'Missing files without a safe match: {unmatched}\\n'
            'Scan errors: {errors}\\n\\n'
            'Original source files were not modified.'
        ).format(
            renamed=renamed, ambiguous=ambiguous, unmatched=unmatched,
            errors=len(result.get('scan_errors', ())),
        )
        info_dialog(self.gui, _('Indexed Library synchronization'), details, show=True)
