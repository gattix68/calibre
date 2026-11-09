#!/usr/bin/env python
# License: GPLv3
from qt.core import QDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTimer, QVBoxLayout

from calibre.gui2 import choose_dir
from calibre.gui2.actions.sync_komga import snapshot
from calibre.utils.localization import _


class SyncKomgaDialog(QDialog):
    def __init__(self, action):
        super().__init__(action.gui)
        self.action = action
        self.db = action.gui.current_db.new_api
        self.plan = self.manager = self.future = None
        self.operation = ''
        self.setWindowTitle(_('Sync Komga Library'))
        self.resize(850, 550)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_('Select an existing, dedicated disposable output folder. Sources remain in Calibre.')))
        row = QHBoxLayout()
        self.output = QLineEdit(action.settings.get(self.db.library_id, ''))
        self.output.setReadOnly(True)
        row.addWidget(self.output)
        self.choose = QPushButton(_('Choose output folder'))
        self.choose.clicked.connect(self.choose_output)
        row.addWidget(self.choose)
        layout.addLayout(row)
        self.status = QLabel(action.status)
        layout.addWidget(self.status)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        layout.addWidget(self.report)
        row = QHBoxLayout()
        self.preview_button = QPushButton(_('Preview changes'))
        self.preview_button.clicked.connect(self.preview)
        row.addWidget(self.preview_button)
        self.apply_button = QPushButton(_('Apply previewed changes'))
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply)
        row.addWidget(self.apply_button)
        self.close_button = QPushButton(_('Close'))
        self.close_button.clicked.connect(self.accept)
        row.addWidget(self.close_button)
        layout.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        if self.output.text():
            self.preview()

    def choose_output(self):
        path = choose_dir(self, 'komga-link-output', _('Choose disposable Komga output directory'))
        if path:
            self.output.setText(path)
            self.plan = None
            self.preview()

    def busy(self, value):
        for button in (self.choose, self.preview_button, self.close_button):
            button.setEnabled(not value)
        self.apply_button.setEnabled(not value and self.plan is not None)

    def preview(self):
        if not self.output.text() or self.future is not None:
            return
        self.plan = None
        self.busy(True)
        self.operation = 'preview'
        self.status.setText(_('Reading metadata, checking sources and output…'))
        self.future = self.action.executor.submit(snapshot, self.db, self.output.text())

    def apply(self):
        if self.plan is None or self.future is not None:
            return
        self.busy(True)
        self.operation = 'apply'
        self.status.setText(_('Synchronizing and verifying links…'))
        self.future = self.action.executor.submit(self.apply_current, self.output.text(), self.plan)

    def apply_current(self, output, plan):
        # Re-read metadata before applying: stale previews never silently sync.
        manager, fresh = snapshot(self.db, output)
        if fresh.state != plan.state:
            raise ValueError('Library or output changed after preview; preview again')
        return manager.apply(plan)

    def poll(self):
        if self.future is None or not self.future.done():
            return
        future, self.future = self.future, None
        try:
            result = future.result()
            if self.operation == 'preview':
                self.manager, self.plan = result
                self.action.settings[self.db.library_id] = self.output.text()
                self.report.setPlainText('\n'.join(f'{x.kind.upper()}: {x.path}\n  → {x.target}' for x in self.plan.changes)
                                         or _('No pending link changes.'))
                self.status.setText(_('Preview: %d pending changes') % len(self.plan.changes)
                                    + (_(' — interrupted run will be reconciled') if self.plan.recovering else ''))
            else:
                self.status.setText(_('Synchronization complete: %d changes; %d links verified') % (len(result.changes), len(result.links)))
                self.report.appendPlainText(self.status.text())
                if result.warnings:
                    self.report.appendPlainText('\n'.join(result.warnings))
                    self.status.setText(self.status.text() + _(' — see warnings below'))
                self.plan = None
        except Exception as err:
            self.status.setText(_('Synchronization error: %s') % str(err))
            self.report.appendPlainText(self.status.text())
            self.plan = None
        self.action.status = self.status.text()
        self.busy(False)

    def reject(self):
        if self.future is None:
            super().reject()

    def done(self, result):
        if self.future is None:
            super().done(result)
