"""Model manager dialog: list, download (with progress), delete, import."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QMessageBox, QProgressBar, QScrollArea, QVBoxLayout, QWidget)

from .. import config
from ..core import models
from . import theme
from .widgets import button, label, repolish
from .workers import DownloadWorker, ImportWorker, OnlineCheck, start_detached


class ModelRow(QFrame):
    downloadRequested = Signal(str)
    deleteRequested = Signal(str)
    cancelRequested = Signal(str)
    importRequested = Signal(str)

    def __init__(self, info: models.ModelInfo, parent=None):
        super().__init__(parent)
        self.info = info
        self.setProperty("card", True)
        g = QGridLayout(self)
        g.setContentsMargins(18, 14, 18, 14)
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(4)

        name = label(info.name)
        name.setFont(theme.display_font(17))
        g.addWidget(name, 0, 0)
        self.badges = label("", "muted")
        self.badges.setTextFormat(Qt.TextFormat.RichText)
        g.addWidget(self.badges, 0, 1, 1, 2)

        stats = label(f"{info.size_mb:,} MB  ·  Speed: {info.speed}  ·  Accuracy: {info.accuracy}  ·  VRAM {info.vram}",
                      "muted")
        g.addWidget(stats, 1, 0, 1, 3)
        notes = label(info.notes, "faint", wrap=True)
        g.addWidget(notes, 2, 0, 1, 3)

        self.bar = QProgressBar()
        self.bar.setProperty("thin", True)
        self.bar.setRange(0, 1000)
        self.bar.hide()
        g.addWidget(self.bar, 3, 0, 1, 3)
        self.status = label("", "faint")
        self.status.hide()
        g.addWidget(self.status, 4, 0, 1, 3)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.dl = button("Download", "accent")
        self.imp = button("Import file…", "ghost")
        self.cancel = button("Cancel", "ghost")
        self.rm = button("Delete", "danger")
        for b in (self.imp, self.dl, self.cancel, self.rm):
            btns.addWidget(b)
        g.addLayout(btns, 0, 3, 3, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        g.setColumnStretch(2, 1)
        self.dl.clicked.connect(lambda: self.downloadRequested.emit(info.name))
        self.rm.clicked.connect(lambda: self.deleteRequested.emit(info.name))
        self.cancel.clicked.connect(lambda: self.cancelRequested.emit(info.name))
        self.imp.clicked.connect(lambda: self.importRequested.emit(info.name))
        self.refresh(False, False)

    def refresh(self, busy: bool, online: bool | None):
        p = theme.current()
        installed = models.is_installed(self.info.name)
        b = []
        if installed:
            b.append(f"<span style='color:{p.success}; font-weight:700'>● INSTALLED</span>")
        if self.info.name == models.DEFAULT_TRANSCRIBE:
            b.append("default for transcription")
        if self.info.name == models.DEFAULT_TRANSLATE:
            b.append("default for translation")
        if not self.info.can_translate:
            b.append(f"<span style='color:{p.warning}'>not for translation</span>")
        self.badges.setText("  ·  ".join(b))
        self.dl.setVisible(not installed and not busy)
        self.dl.setEnabled(online is not False)
        self.dl.setToolTip("" if online is not False else "Offline – connect to download more models.")
        part = models.path_for(self.info.name).with_suffix(".bin.part")
        self.dl.setText("Resume" if part.exists() else "Download")
        self.imp.setVisible(not installed and not busy)
        self.rm.setVisible(installed and not busy)
        self.cancel.setVisible(busy)
        self.bar.setVisible(busy)
        if not busy:
            self.status.hide()

    def setProgress(self, done: int, total: int, phase: str):
        self.bar.show()
        self.status.show()
        self.bar.setValue(int(done / max(1, total) * 1000))
        if phase == "verify":
            self.status.setText(f"Verifying checksum… {done / max(1, total) * 100:.0f}%")
        else:
            self.status.setText(f"Downloading… {done / 1e6:,.0f} / {total / 1e6:,.0f} MB "
                                f"({done / max(1, total) * 100:.0f}%)")

    def setMessage(self, text: str, role: str = "faint"):
        self.status.setText(text)
        self.status.setProperty("role", role)
        repolish(self.status)
        self.status.show()


class ModelManager(QDialog):
    modelsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Model Manager – AutoSub9000")
        self.resize(860, 680)
        self.online: bool | None = None
        self.worker: DownloadWorker | None = None
        self.busy: set[str] = set()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(14)
        title = label("Whisper Models")
        title.setFont(theme.display_font(26))
        lay.addWidget(title)
        self.net = label("Checking connection…", "muted")
        lay.addWidget(self.net)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 6, 0)
        il.setSpacing(10)
        self.rows: dict[str, ModelRow] = {}
        for info in models.CATALOGUE:
            r = ModelRow(info)
            r.downloadRequested.connect(self.download)
            r.deleteRequested.connect(self.delete)
            r.cancelRequested.connect(self.cancel)
            r.importRequested.connect(self.import_file)
            il.addWidget(r)
            self.rows[info.name] = r
        il.addStretch(1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        self.disk = label("", "faint")
        bottom.addWidget(self.disk)
        bottom.addStretch(1)
        folder = button("Open models folder", "ghost")
        folder.clicked.connect(self._open_folder)
        bottom.addWidget(folder)
        close = button("Close")
        close.clicked.connect(self.close)
        bottom.addWidget(close)
        lay.addLayout(bottom)

        self._refresh()
        self._check = start_detached(OnlineCheck())
        self._check.result.connect(self._on_online)

    def _on_online(self, ok: bool):
        self.online = ok
        if ok:
            self.net.setText("Online – models download from huggingface.co and are verified by checksum.")
            self.net.setProperty("role", "muted")
        else:
            self.net.setText("Offline – connect to download more models.")
            self.net.setProperty("role", "warning")
        repolish(self.net)
        self._refresh()

    def _refresh(self):
        for name, r in self.rows.items():
            r.refresh(name in self.busy, self.online)
        d = config.models_dir()
        d.mkdir(parents=True, exist_ok=True)
        used = sum(f.stat().st_size for f in d.glob("*.bin"))
        free = shutil.disk_usage(d).free
        self.disk.setText(f"{d}  ·  {used / 1e9:.1f} GB used  ·  {free / 1e9:.0f} GB free")

    def _open_folder(self):
        d = config.models_dir()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def download(self, name: str):
        if self.worker and self.worker.isRunning():
            # queue: simply start another worker after the current one
            self.worker.allDone.connect(lambda n=name: self.download(n))
            self.rows[name].setMessage("Queued…")
            return
        self.busy.add(name)
        self._refresh()
        self.worker = DownloadWorker([name], self)
        self.worker.progress.connect(lambda n, d, t, ph: self.rows[n].setProgress(d, t, ph))
        self.worker.finished_one.connect(self._done)
        self.worker.start()

    def _done(self, name: str, ok: bool, msg: str, hint: str):
        self.busy.discard(name)
        self._refresh()
        if ok:
            self.rows[name].setMessage("Installed and verified ✔", "success")
        else:
            self.rows[name].setMessage(f"{msg} {hint}".strip(), "error" if msg != "Cancelled" else "faint")
        self.modelsChanged.emit()

    def cancel(self, name: str):
        if self.worker:
            self.worker.cancel()

    def delete(self, name: str):
        info = models.get(name)
        if QMessageBox.question(self, "Delete model",
                                f"Delete {name} ({info.size_mb:,} MB)?\nYou can download it again later.") \
                != QMessageBox.StandardButton.Yes:
            return
        models.delete(name)
        self._refresh()
        self.modelsChanged.emit()

    def import_file(self, name: str):
        info = models.get(name)
        path, _ = QFileDialog.getOpenFileName(self, f"Import {info.filename}", str(Path.home()),
                                              "Whisper ggml model (*.bin)")
        if not path:
            return
        self.busy.add(name)
        self._refresh()
        self.rows[name].setMessage("Verifying checksum…")
        w = ImportWorker(name, Path(path), self)
        w.progress.connect(lambda f: self.rows[name].setProgress(int(f * 1000), 1000, "verify"))
        w.done.connect(self._imported)
        start_detached(w)

    def _imported(self, name: str, ok: bool, msg: str):
        self.busy.discard(name)
        self._refresh()
        self.rows[name].setMessage("Imported and verified ✔" if ok else msg, "success" if ok else "error")
        self.modelsChanged.emit()

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            if QMessageBox.question(self, "Download in progress",
                                    "Stop the download? It will resume next time.") \
                    != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.worker.cancel()
            self.worker.wait(5000)
        super().closeEvent(e)

