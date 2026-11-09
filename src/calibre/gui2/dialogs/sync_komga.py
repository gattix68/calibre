#!/usr/bin/env python
# License: GPLv3
import os
from collections import Counter

from qt.core import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTimer,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from calibre.gui2 import choose_dir, open_local_file
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
        self.resize(1150, 720)
        layout = QVBoxLayout(self)
        intro = QLabel(_('Choose a dedicated output folder. Review the metadata and proposed links, then click Apply. Original books stay in Calibre.'))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QHBoxLayout()
        row.addWidget(QLabel(_('Destination:')))
        self.output = QLineEdit(action.settings.get(self.db.library_id, ''))
        self.output.setReadOnly(True)
        self.output.setPlaceholderText(_('Choose an existing disposable output folder'))
        row.addWidget(self.output)
        self.choose = QPushButton(_('Choose output folder…'))
        self.choose.clicked.connect(self.choose_output)
        row.addWidget(self.choose)
        self.open_output = QPushButton(_('Open output folder'))
        self.open_output.clicked.connect(self.open_output_folder)
        row.addWidget(self.open_output)
        layout.addLayout(row)
        self.status = QLabel(action.status)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.metadata_help = QLabel(_('Series folders use Calibre’s Series field. Volume order uses Series index. Titles and book IDs identify each link.'))
        self.metadata_help.setWordWrap(True)
        layout.addWidget(self.metadata_help)
        self.tabs = QTabWidget()
        self.metadata_tree = QTreeWidget()
        self.metadata_tree.setHeaderLabels([_('Series / book'), _('Volume'), _('Calibre ID'), _('Authors'), _('Formats'), _('Original file location')])
        self.metadata_tree.setAlternatingRowColors(True)
        self.tabs.addTab(self.metadata_tree, _('Books and volumes'))
        self.link_tree = QTreeWidget()
        self.link_tree.setHeaderLabels([_('Proposed folders and symbolic links'), _('Change'), _('Links to original file')])
        self.link_tree.setAlternatingRowColors(True)
        self.tabs.addTab(self.link_tree, _('Preview: folders and links'))
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.tabs.addTab(self.report, _('Results and errors'))
        layout.addWidget(self.tabs)
        self.open_after_sync = QCheckBox(_('Open the destination in the file manager after successful synchronization'))
        self.open_after_sync.setChecked(True)
        layout.addWidget(self.open_after_sync)
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
        self.busy(False)
        if self.output.text():
            self.preview()

    def choose_output(self):
        path = choose_dir(self, 'komga-link-output', _('Choose disposable Komga output directory'), default_dir=self.output.text() or None)
        if path:
            self.output.setText(path)
            self.plan = None
            self.preview()

    def open_output_folder(self):
        path = self.output.text()
        if path and os.path.isdir(path):
            open_local_file(path)

    def busy(self, value):
        for button in (self.choose, self.preview_button, self.close_button):
            button.setEnabled(not value)
        self.open_output.setEnabled(not value and os.path.isdir(self.output.text()))
        self.apply_button.setEnabled(not value and self.plan is not None)

    def preview(self):
        if not self.output.text() or self.future is not None:
            return
        self.plan = None
        self.metadata_tree.clear()
        self.link_tree.clear()
        self.busy(True)
        self.operation = 'preview'
        self.status.setText(_('Reading metadata, checking sources and output…'))
        self.future = self.action.executor.submit(snapshot, self.db, self.output.text())

    def show_preview(self, books):
        plan = self.plan
        assert plan is not None
        groups = {}
        supported = [book for book in books if book.formats]
        for book in sorted(supported, key=lambda b: ((b.series or b.title).casefold(), b.series_index, b.book_id)):
            series = book.series or _('No series — individual book folders')
            if series not in groups:
                groups[series] = QTreeWidgetItem(self.metadata_tree, [series])
            sources = '\n'.join(path for fmt, path in book.formats)
            row = QTreeWidgetItem(
                groups[series],
                [book.title, f'{book.series_index:g}', str(book.book_id), ', '.join(book.authors), ', '.join(fmt for fmt, path in book.formats), sources],
            )
            row.setToolTip(0, book.title)
            row.setToolTip(5, sources)
        self.metadata_tree.expandAll()
        self.metadata_tree.setColumnWidth(0, 380)
        for column in (1, 2, 3, 4):
            self.metadata_tree.resizeColumnToContents(column)
        self.metadata_tree.setColumnWidth(3, 180)
        self.metadata_tree.setColumnWidth(5, 420)
        for tree in (self.metadata_tree, self.link_tree):
            header = tree.header()
            assert header is not None
            header.setStretchLastSection(False)
        folders = {}
        desired_changes = {change.path: change.kind for change in plan.changes if change.kind != 'removal'}
        rows = [(link.path, desired_changes.get(link.path, _('Unchanged')), link.target) for link in plan.links]
        rows.extend((change.path, change.kind, change.target) for change in plan.changes if change.kind == 'removal')
        root = QTreeWidgetItem(self.link_tree, [self.output.text()])
        for path, kind, target in sorted(rows):
            folder, filename = path.split('/')
            if folder not in folders:
                folders[folder] = QTreeWidgetItem(root, [folder])
            row = QTreeWidgetItem(folders[folder], [filename, kind, target])
            row.setToolTip(0, path)
            row.setToolTip(2, target)
        self.link_tree.expandAll()
        self.link_tree.setColumnWidth(0, 620)
        self.link_tree.resizeColumnToContents(1)
        self.link_tree.setColumnWidth(2, 600)
        counts = Counter(change.kind for change in plan.changes)
        summary = _('Preview: {books} books, {links} links; {changes} pending changes').format(
            books=len(supported), links=len(plan.links), changes=len(plan.changes)
        )
        if counts:
            summary += ' — ' + ', '.join(f'{kind}: {count}' for kind, count in sorted(counts.items()))
        if plan.recovering:
            summary += _(' — interrupted run will be reconciled')
        self.status.setText(summary)
        self.report.setPlainText('\n'.join(f'{x.kind.upper()}: {x.path}\n  → {x.target}' for x in plan.changes) or _('No pending link changes.'))
        self.tabs.setCurrentWidget(self.link_tree)

    def apply(self):
        if self.plan is None or self.future is not None:
            return
        self.busy(True)
        self.operation = 'apply'
        self.status.setText(_('Synchronizing and verifying links…'))
        self.future = self.action.executor.submit(self.apply_current, self.output.text(), self.plan)

    def apply_current(self, output, plan):
        # Re-read metadata before applying: stale previews never silently sync.
        manager, fresh, books = snapshot(self.db, output)
        if fresh.state != plan.state:
            raise ValueError('Library or output changed after preview; preview again')
        return manager.apply(plan)

    def poll(self):
        if self.future is None or not self.future.done():
            return
        future, self.future = self.future, None
        succeeded = False
        try:
            result = future.result()
            if self.operation == 'preview':
                self.manager, self.plan, books = result
                self.action.settings[self.db.library_id] = self.output.text()
                self.show_preview(books)
            else:
                self.status.setText(_('Synchronization complete: %d changes; %d links verified') % (len(result.changes), len(result.links)))
                self.report.appendPlainText(self.status.text())
                if result.warnings:
                    self.report.appendPlainText('\n'.join(result.warnings))
                    self.status.setText(self.status.text() + _(' — see warnings below'))
                self.plan = None
                self.tabs.setCurrentWidget(self.report)
                succeeded = True
        except Exception as err:
            self.status.setText(_('Synchronization error: %s') % str(err))
            self.report.appendPlainText(self.status.text())
            self.tabs.setCurrentWidget(self.report)
            self.plan = None
        self.action.status = self.status.text()
        self.busy(False)
        if succeeded and self.open_after_sync.isChecked():
            self.open_output_folder()

    def reject(self):
        if self.future is None:
            super().reject()

    def done(self, a0: int) -> None:
        if self.future is None:
            super().done(a0)
