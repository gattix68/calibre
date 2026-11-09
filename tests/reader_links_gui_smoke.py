#!/usr/bin/env python
# License: GPLv3
"""Run with calibre-debug -e in an isolated config and offscreen Qt process."""

import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qt.core import QAction, QApplication, QWidget

from calibre.db.backend import DB
from calibre.db.cache import Cache
from calibre.ebooks.metadata.book.base import Metadata
from calibre.gui2 import gprefs
from calibre.gui2.actions.sync_komga import SyncKomgaAction
from calibre.gui2.dialogs.sync_komga import SyncKomgaDialog


class TestGUI(QWidget):
    current_db: SimpleNamespace
    bars_manager: SimpleNamespace


def main() -> None:
    app = QApplication([])
    startup_gui = TestGUI()
    startup_action = SyncKomgaAction(startup_gui, None)
    startup_action.qaction = QAction(startup_gui)
    startup_action.genesis()
    startup_action.poll()
    assert startup_action.future is None, 'Monitoring ran before GUI database initialization'
    startup_action.shutting_down()
    with tempfile.TemporaryDirectory() as root:
        source, output = Path(root) / 'books', Path(root) / 'output'
        source.mkdir()
        output.mkdir()
        db = Cache(DB(str(source)))
        db.init()
        page_counts = db.maintain_page_counts
        assert page_counts is not None
        page_counts.shutdown()
        page_counts.wait_for_worker_shutdown()
        queue_scan = patch.object(page_counts, 'queue_scan')
        queue_scan.start()
        try:
            bid = db.create_book_entry(Metadata('Iron Man', ['Matt Fraction']))
            db.set_field('series', {bid: 'Iron Man'})
            db.add_format(bid, 'CBZ', BytesIO(b'comic'), run_hooks=False)
            gui = TestGUI()
            gui.current_db = SimpleNamespace(new_api=db)
            with ThreadPoolExecutor(max_workers=1) as executor:
                action = SimpleNamespace(gui=gui, settings={db.library_id: str(output)}, executor=executor, status='Waiting')
                dialog = SyncKomgaDialog(action)
                dialog.show()

                def wait() -> None:
                    deadline = time.monotonic() + 30
                    while dialog.future is not None and time.monotonic() < deadline:
                        app.processEvents()
                        time.sleep(0.02)
                    assert dialog.future is None, 'UI worker timeout'

                wait()
                assert dialog.plan is not None, dialog.status.text()
                assert 'ADDITION' in dialog.report.toPlainText()
                assert dialog.apply_button.isEnabled()
                dialog.apply()
                wait()
                assert 'Synchronization complete' in dialog.status.text(), dialog.report.toPlainText()
                dialog.preview()
                wait()
                assert not dialog.plan.changes
                dialog.close()

            action = SyncKomgaAction(gui, None)
            action.qaction = QAction(gui)
            action.genesis()
            action.settings[db.library_id] = str(output)
            action.settings['toolbar-installed'] = False
            gprefs['action-layout-toolbar'] = ('Choose Library',)
            calls = []
            gui.bars_manager = SimpleNamespace(init_bars=lambda: calls.append('init'), update_bars=lambda: calls.append('update'))
            action.initialization_complete()
            assert gprefs['action-layout-toolbar'] == ('Choose Library', 'Sync Komga Library')
            assert calls == ['init', 'update']
            action.timer.stop()
            before = {str(p): (p.lstat().st_mtime_ns, p.lstat().st_size) for p in output.rglob('*')}
            action.poll()
            deadline = time.monotonic() + 30
            while action.future is not None and time.monotonic() < deadline:
                action.poll()
                time.sleep(0.02)
            assert action.future is None
            assert action.status == 'Pending changes: 0', action.status
            after = {str(p): (p.lstat().st_mtime_ns, p.lstat().st_size) for p in output.rglob('*')}
            assert before == after, 'Monitoring mutated output'
            action.shutting_down()
        finally:
            queue_scan.stop()
            db.close()
    print('GUI preview/apply/results/repeat, toolbar migration and read-only monitoring passed')


if __name__ == '__main__':
    main()
