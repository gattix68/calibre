#!/usr/bin/env python
# License: GPLv3
import os
from concurrent.futures import ThreadPoolExecutor

from qt.core import QTimer

from calibre.db.reader_links import LinkManager, komga_layout, read_books
from calibre.gui2.actions import InterfaceAction
from calibre.utils.config import JSONConfig
from calibre.utils.localization import _


def snapshot(db, output):
    manager = LinkManager(output, db.library_id, (db.backend.library_path, os.path.dirname(db.backend.dbpath)))
    books = read_books(db)
    return manager, manager.preview(komga_layout(books))


class SyncKomgaAction(InterfaceAction):
    name = 'Sync Komga Library'
    action_spec = (_('Sync Komga Library'), 'refresh.png', _('Preview and synchronize the Komga link library'), None)
    dont_add_to = frozenset(('context-menu-device', 'menubar-device', 'toolbar-device'))

    def genesis(self):
        self.settings = JSONConfig('komga-link-manager')
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='komga-preview')
        self.future = None
        self.dialog = None
        self.status = _('Choose a disposable output directory to begin')
        self.qaction.triggered.connect(self.show_dialog)
        self.timer = QTimer(self.gui)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.ticks = 29

    def initialization_complete(self):
        # One-time migration for profiles whose customized toolbar predates this action.
        from calibre.gui2 import gprefs
        if not self.settings.get('toolbar-installed', False):
            layout = list(gprefs['action-layout-toolbar'])
            if self.name not in layout:
                layout.append(self.name)
                gprefs['action-layout-toolbar'] = tuple(layout)
                self.gui.bars_manager.init_bars()
                self.gui.bars_manager.update_bars()
            self.settings['toolbar-installed'] = True

    def shutting_down(self):
        self.timer.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def library_changed(self, db):
        self.status = _('Library changed; awaiting preview')
        self.ticks = 29

    def poll(self):
        if self.dialog is not None:
            return
        self.ticks += 1
        if self.future is not None:
            if not self.future.done():
                return
            library_id, future = self.future_library, self.future
            self.future = None
            if library_id == self.gui.current_db.new_api.library_id:
                try:
                    plan = future.result()[1]
                    self.status = _('Pending changes: %d') % len(plan.changes)
                    if plan.recovering:
                        self.status += _(' (interrupted synchronization; retry available)')
                except Exception as err:
                    self.status = _('Monitoring error: %s') % str(err)
                self.qaction.setToolTip(self.status)
        if self.ticks >= 30 and self.future is None:
            self.ticks = 0
            db = self.gui.current_db.new_api
            output = self.settings.get(db.library_id)
            if output:
                self.future_library = db.library_id
                self.future = self.executor.submit(snapshot, db, output)

    def show_dialog(self):
        from calibre.gui2.dialogs.sync_komga import SyncKomgaDialog
        if self.dialog is None:
            self.dialog = SyncKomgaDialog(self)
            try:
                self.dialog.exec()
            finally:
                self.dialog = None
                self.ticks = 29
