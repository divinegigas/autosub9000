"""'Check for updates' dialog. Only ever opened by the user."""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QProcess, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QProgressBar, QTextBrowser,
                               QVBoxLayout)

from .. import __version__
from ..core import updater
from ..core.errors import Cancelled, friendly
from . import theme
from .widgets import button, label, repolish


class _Check(QThread):
    done = Signal(object, str, str)  # Release|None, error message, hint

    def run(self):
        try:
            self.done.emit(updater.check(), "", "")
        except Exception as e:  # noqa: BLE001
            err = friendly(e)
            self.done.emit(None, err.message, err.hint)


class _Install(QThread):
    progress = Signal(int, int)
    done = Signal(bool, str, str)

    def __init__(self, rel, parent=None):
        super().__init__(parent)
        self.rel = rel
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            updater.install(self.rel, self.progress.emit, self._cancel.is_set)
            self.done.emit(True, "", "")
        except Cancelled:
            self.done.emit(False, "Cancelled.", "Nothing was changed.")
        except Exception as e:  # noqa: BLE001
            err = friendly(e)
            self.done.emit(False, err.message, err.hint)


class UpdateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Updates – AutoSub9000")
        self.setMinimumSize(620, 460)
        self.rel = None
        self.worker = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(12)
        t = label("Updates")
        t.setFont(theme.display_font(26))
        lay.addWidget(t)
        self.status = label(f"You have version {__version__}. Checking GitHub for a newer one…", "muted",
                            wrap=True)
        lay.addWidget(self.status)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.hide()
        lay.addWidget(self.notes, 1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.detail = label("", "faint", wrap=True)
        lay.addWidget(self.detail)
        lay.addStretch(1)

        row = QHBoxLayout()
        self.page_btn = button("Release page", "ghost")
        self.page_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl(self.rel.page_url if self.rel else updater.RELEASES_PAGE)))
        row.addWidget(self.page_btn)
        row.addStretch(1)
        self.close_btn = button("Close", "ghost")
        self.close_btn.clicked.connect(self.close)
        row.addWidget(self.close_btn)
        self.action = button("Check again", "accent")
        self.action.setMinimumWidth(190)
        self.action.clicked.connect(self._action)
        row.addWidget(self.action)
        lay.addLayout(row)
        self._mode = "check"
        self._check()

    def _set_status(self, text: str, role: str = "muted"):
        self.status.setText(text)
        self.status.setProperty("role", role)
        repolish(self.status)

    def _check(self):
        self._mode = "checking"
        self.action.setEnabled(False)
        self.worker = _Check(self)
        self.worker.done.connect(self._checked)
        self.worker.start()

    def _checked(self, rel, msg: str, hint: str):
        self.action.setEnabled(True)
        self.rel = rel
        if msg:
            self._set_status(f"{msg} {hint}".strip(), "warning")
            self._mode = "check"
            self.action.setText("Check again")
            return
        if rel is None:
            self._set_status(f"You have version {__version__}. No releases have been published yet.")
            self._mode = "check"
            self.action.setText("Check again")
            return
        if not rel.is_newer:
            self._set_status(f"You're up to date – version {__version__} is the latest. ✔", "success")
            self._mode = "check"
            self.action.setText("Check again")
            return
        self._set_status(f"Version {rel.version} is available (you have {__version__}).", "success")
        if rel.notes:
            self.notes.setMarkdown(f"### What's new in {rel.version}\n\n{rel.notes}")
            self.notes.show()
        size = f"{rel.size / 1e6:.0f} MB" if rel.size else ""
        if updater.appimage_path() is None:
            self.detail.setText("You're running from source, so the AppImage can't replace itself. "
                                "Use git pull, or download the AppImage from the release page.")
            self.action.setEnabled(False)
            self.action.setText("Install update")
            return
        self.detail.setText(f"Downloads {size} and replaces {updater.appimage_path()} after verifying "
                            "its SHA-256 checksum. Your settings and models are kept.")
        self._mode = "install"
        self.action.setText("Download && install")

    def _action(self):
        if self._mode == "check":
            self._set_status("Checking GitHub…")
            self._check()
        elif self._mode == "install":
            self._install()
        elif self._mode == "installing":
            self.worker.cancel()
        elif self._mode == "restart":
            self._restart()

    def _install(self):
        self._mode = "installing"
        self.action.setText("Cancel")
        self.action.setProperty("kind", "danger")
        repolish(self.action)
        self.bar.show()
        self.worker = _Install(self.rel, self)
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._installed)
        self.worker.start()

    def _progress(self, done: int, total: int):
        self.bar.setValue(int(done / max(1, total) * 1000))
        self.detail.setText(f"Downloading… {done / 1e6:.0f} / {total / 1e6:.0f} MB")

    def _installed(self, ok: bool, msg: str, hint: str):
        self.action.setProperty("kind", "accent")
        repolish(self.action)
        if ok:
            self.bar.setValue(1000)
            self._set_status(f"Version {self.rel.version} is installed. ✔", "success")
            self.detail.setText("Restart AutoSub9000 to use it.")
            self._mode = "restart"
            self.action.setText("Restart now")
        else:
            self.bar.hide()
            self._set_status(f"{msg} {hint}".strip(), "warning" if msg == "Cancelled." else "error")
            self.detail.setText("")
            self._mode = "install"
            self.action.setText("Try again")

    def _restart(self):
        win = self.parent()
        if win is not None and getattr(win, "worker", None) is not None and win.worker.isRunning():
            self.detail.setText("A job is still running – restart when it has finished.")
            return
        target = str(updater.appimage_path())
        env_args = []
        if os.environ.get("APPIMAGE_EXTRACT_AND_RUN") == "1":
            env_args = ["--appimage-extract-and-run"]
        if QProcess.startDetached(target, env_args):
            self.accept()
            if win is not None:
                win.close()
            QApplication.instance().quit()
        else:
            self.detail.setText("Couldn't start the new version – please start it from your menu.")

    def closeEvent(self, e):
        if self._mode == "installing" and self.worker:
            self.worker.cancel()
            self.worker.wait(5000)
        super().closeEvent(e)
