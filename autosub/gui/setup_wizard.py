"""First-run setup: pick models, download with progress, verify checksums."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QProgressBar,
                               QStackedWidget, QVBoxLayout, QWidget)

from .. import config
from ..core import models
from . import theme
from .widgets import button, card, fmt_duration, label, repolish, section
from .workers import DownloadWorker, ImportWorker, OnlineCheck, start_detached


class SetupWizard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to AutoSub9000")
        self.setMinimumSize(720, 600)
        self.online: bool | None = None
        self.worker: DownloadWorker | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 30, 36, 26)
        lay.setSpacing(16)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.stack.addWidget(self._page_welcome())
        self.stack.addWidget(self._page_pick())
        self.stack.addWidget(self._page_download())
        self.stack.addWidget(self._page_done())

        nav = QHBoxLayout()
        self.skip = button("Skip for now", "ghost")
        self.skip.clicked.connect(self._skip)
        nav.addWidget(self.skip)
        nav.addStretch(1)
        self.back = button("Back", "ghost")
        self.back.clicked.connect(lambda: self._go(self.stack.currentIndex() - 1))
        self.next = button("Let's go", "accent")
        self.next.setMinimumWidth(150)
        self.next.clicked.connect(self._next)
        nav.addWidget(self.back)
        nav.addWidget(self.next)
        lay.addLayout(nav)

        self._check = start_detached(OnlineCheck())
        self._check.result.connect(self._on_online)
        self._go(0)

    # ------------------------------------------------------------------ pages
    def _page_welcome(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(14)
        v.addStretch(1)
        icon = label("")
        pm = QPixmap(str(theme.assets_dir() / "autosub9000.svg"))
        if not pm.isNull():
            icon.setPixmap(pm.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(icon)
        t = label("AUTOSUB 9000")
        t.setFont(theme.deco_font(40))
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(t)
        s = label("Subtitles with style. Fully offline.", "muted")
        s.setFont(theme.display_font(16))
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(s)
        body = label("AutoSub9000 runs Whisper entirely on your machine – your GPU when it can, your CPU "
                     "when it can't. It only needs the internet once, to download the speech models you "
                     "pick on the next page. After that, it never goes online.", "muted", wrap=True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setMaximumWidth(560)
        hb = QHBoxLayout()
        hb.addStretch(1)
        hb.addWidget(body)
        hb.addStretch(1)
        v.addLayout(hb)
        v.addStretch(2)
        return w

    def _page_pick(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(10)
        t = label("Choose your models")
        t.setFont(theme.display_font(26))
        v.addWidget(t)
        v.addWidget(label("You can add or remove models any time in the Model Manager.", "muted"))
        self.net_label = label("Checking connection…", "faint")
        v.addWidget(self.net_label)
        self.checks: dict[str, QCheckBox] = {}
        c = card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(18, 14, 18, 14)
        cl.setSpacing(4)
        for info in models.CATALOGUE:
            row = QHBoxLayout()
            cb = QCheckBox(f"{info.name}")
            cb.setFont(theme.display_font(15))
            cb.setChecked(info.name in (models.DEFAULT_TRANSCRIBE, models.DEFAULT_TRANSLATE))
            if models.is_installed(info.name):
                cb.setChecked(False)
                cb.setEnabled(False)
                cb.setText(f"{info.name}  (installed)")
            cb.toggled.connect(self._update_total)
            self.checks[info.name] = cb
            row.addWidget(cb)
            row.addStretch(1)
            row.addWidget(label(f"{info.size_mb:,} MB", "muted"))
            cl.addLayout(row)
            extra = ""
            if info.name == models.DEFAULT_TRANSCRIBE:
                extra = " Recommended for transcription."
            elif info.name == models.DEFAULT_TRANSLATE:
                extra = " Recommended for translation to English."
            note = label(f"{info.speed} · {info.accuracy} accuracy. {info.notes}{extra}", "faint", wrap=True)
            note.setContentsMargins(28, 0, 0, 8)
            cl.addWidget(note)
        v.addWidget(c, 1)
        self.total = label("", "muted")
        v.addWidget(self.total)
        imp = button("I already have model files – import…", "ghost")
        imp.clicked.connect(self._import)
        v.addWidget(imp, 0, Qt.AlignmentFlag.AlignLeft)
        self._update_total()
        return w

    def _page_download(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(12)
        t = label("Downloading")
        t.setFont(theme.display_font(26))
        v.addWidget(t)
        self.dl_info = label("", "muted")
        v.addWidget(self.dl_info)
        self.dl_box = QVBoxLayout()
        self.dl_box.setSpacing(12)
        v.addLayout(self.dl_box)
        v.addSpacing(6)
        v.addWidget(section("Overall"))
        self.overall = QProgressBar()
        self.overall.setRange(0, 1000)
        v.addWidget(self.overall)
        self.overall_text = label("", "faint")
        v.addWidget(self.overall_text)
        v.addStretch(1)
        self.bars: dict[str, tuple[QProgressBar, object]] = {}
        return w

    def _page_done(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addStretch(1)
        self.done_title = label("Ready.")
        self.done_title.setFont(theme.deco_font(44))
        self.done_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.done_title)
        self.done_text = label("", "muted", wrap=True)
        self.done_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.done_text)
        v.addStretch(2)
        return w

    # ------------------------------------------------------------------ logic
    def _selected(self) -> list[str]:
        return [n for n, cb in self.checks.items() if cb.isChecked() and cb.isEnabled()]

    def _update_total(self):
        sel = self._selected()
        mb = sum(models.get(n).size_mb for n in sel)
        d = config.models_dir()
        probe = d if d.exists() else Path.home()
        free = shutil.disk_usage(probe).free / 1e9
        self.total.setText(f"Selected: {len(sel)} model(s), {mb / 1000:.1f} GB  ·  {free:.0f} GB free  ·  saved to {d}")
        if self.stack.currentIndex() == 1:
            self.next.setEnabled(bool(sel) and self.online is not False)

    def _on_online(self, ok: bool):
        self.online = ok
        if ok:
            self.net_label.setText("Online – ready to download.")
            self.net_label.setProperty("role", "success")
        else:
            self.net_label.setText("Offline – connect to the internet to download models, "
                                   "or import model files you already have.")
            self.net_label.setProperty("role", "warning")
        repolish(self.net_label)
        self._update_total()

    def _go(self, idx: int):
        idx = max(0, min(3, idx))
        self.stack.setCurrentIndex(idx)
        self.back.setVisible(idx == 1)
        self.skip.setVisible(idx in (0, 1))
        self.next.setEnabled(True)
        self.next.setText({0: "Let's go", 1: "Download", 2: "Cancel", 3: "Start"}[idx])
        self.next.setProperty("kind", "danger" if idx == 2 else "accent")
        repolish(self.next)
        if idx == 1:
            self._update_total()

    def _next(self):
        i = self.stack.currentIndex()
        if i == 0:
            self._go(1)
        elif i == 1:
            self._start_download()
        elif i == 2:
            if self.worker:
                self.worker.cancel()
        else:
            self._finish()

    def _start_download(self):
        names = self._selected()
        if not names:
            return
        self._go(2)
        while self.dl_box.count():
            item = self.dl_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.bars.clear()
        self.sizes = {n: models.get(n).size_mb * 1024 * 1024 for n in names}
        self.done_bytes = {n: 0 for n in names}
        for n in names:
            c = card()
            cl = QVBoxLayout(c)
            cl.setContentsMargins(16, 12, 16, 12)
            head = QHBoxLayout()
            nm = label(n)
            nm.setFont(theme.display_font(16))
            head.addWidget(nm)
            head.addStretch(1)
            st = label("Waiting…", "faint")
            head.addWidget(st)
            cl.addLayout(head)
            bar = QProgressBar()
            bar.setProperty("thin", True)
            bar.setRange(0, 1000)
            cl.addWidget(bar)
            self.dl_box.addWidget(c)
            self.bars[n] = (bar, st)
        self.t0 = time.monotonic()
        self.dl_info.setText(f"Saving to {config.models_dir()}")
        self.results: dict[str, tuple[bool, str]] = {}
        self.worker = DownloadWorker(names, self)
        self.worker.progress.connect(self._progress)
        self.worker.finished_one.connect(self._one_done)
        self.worker.allDone.connect(self._all_done)
        self.worker.start()

    def _progress(self, name: str, done: int, total: int, phase: str):
        bar, st = self.bars[name]
        bar.setValue(int(done / max(1, total) * 1000))
        if phase == "verify":
            st.setText(f"Verifying checksum… {done / max(1, total) * 100:.0f}%")
            self.done_bytes[name] = self.sizes[name]
        else:
            self.sizes[name] = total
            self.done_bytes[name] = done
            st.setText(f"{done / 1e6:,.0f} / {total / 1e6:,.0f} MB")
        tot = sum(self.sizes.values())
        dn = sum(self.done_bytes.values())
        f = dn / max(1, tot)
        self.overall.setValue(int(f * 1000))
        el = time.monotonic() - self.t0
        speed = dn / max(0.5, el)
        eta = (tot - dn) / speed if speed > 0 else float("inf")
        self.overall_text.setText(f"{f * 100:.0f}%  ·  {speed / 1e6:.1f} MB/s  ·  "
                                  f"elapsed {fmt_duration(el)}  ·  ETA {fmt_duration(eta)}")

    def _one_done(self, name: str, ok: bool, msg: str, hint: str):
        bar, st = self.bars[name]
        self.results[name] = (ok, msg)
        if ok:
            bar.setValue(1000)
            st.setText("Verified ✔")
            st.setProperty("role", "success")
        else:
            st.setText(msg)
            st.setProperty("role", "error")
            st.setToolTip(hint)
        repolish(st)

    def _all_done(self):
        ok = [n for n, (good, _) in self.results.items() if good]
        failed = [(n, m) for n, (good, m) in self.results.items() if not good]
        if models.installed():
            s = config.Settings.load()
            s.setup_done = True
            inst = models.installed()
            if s.transcribe_model not in inst:
                s.transcribe_model = inst[0] if models.DEFAULT_TRANSCRIBE not in inst else models.DEFAULT_TRANSCRIBE
            if s.translate_model not in inst and models.best_translate_model():
                s.translate_model = models.best_translate_model()
            s.save()
        if failed and not ok:
            self.done_title.setText("Not quite.")
            self.done_text.setText("The downloads didn't finish:\n" +
                                   "\n".join(f"{n}: {m}" for n, m in failed) +
                                   "\n\nYou can retry in the Model Manager – downloads resume where they stopped.")
        else:
            self.done_title.setText("Ready.")
            extra = ("\n\nNot finished: " + ", ".join(n for n, _ in failed)) if failed else ""
            self.done_text.setText(f"Installed: {', '.join(ok) or '—'}. Everything from here on runs offline."
                                   + extra)
        self._go(3)

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Whisper model", str(Path.home()),
                                              "Whisper ggml model (ggml-*.bin)")
        if not path:
            return
        fname = Path(path).name
        match = next((m.name for m in models.CATALOGUE if m.filename == fname), None)
        if not match:
            self.net_label.setText(f"“{fname}” isn't one of the known model files "
                                   f"({', '.join(m.filename for m in models.CATALOGUE)}).")
            self.net_label.setProperty("role", "error")
            repolish(self.net_label)
            return
        self.net_label.setText(f"Verifying {fname}…")
        w = ImportWorker(match, Path(path), self)
        w.done.connect(self._imported)
        start_detached(w)

    def _imported(self, name: str, ok: bool, msg: str):
        cb = self.checks[name]
        if ok:
            cb.setChecked(False)
            cb.setEnabled(False)
            cb.setText(f"{name}  (installed)")
            self.net_label.setText(f"{name} imported and verified ✔")
            self.net_label.setProperty("role", "success")
            s = config.Settings.load()
            s.setup_done = True
            s.save()
        else:
            self.net_label.setText(msg)
            self.net_label.setProperty("role", "error")
        repolish(self.net_label)
        self._update_total()

    def _skip(self):
        s = config.Settings.load()
        s.setup_done = True
        s.save()
        self.accept()

    def _finish(self):
        self.accept()

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)
        super().closeEvent(e)
