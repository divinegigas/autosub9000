"""Main window: drop zone → settings → GENERATE → progress with style rank."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl, QVariantAnimation
from PySide6.QtGui import QColor, QDesktopServices, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame,
                               QGraphicsDropShadowEffect, QHBoxLayout, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from .. import config
from ..core import models
from ..core.languages import sorted_choices
from ..core.media import VIDEO_EXTENSIONS
from ..core.pipeline import JobOptions, translation_model_check
from ..core.subtitles import format_ts
from . import theme
from .notify import notify
from .widgets import (DropZone, LogPanel, Segmented, StyleMeter, button, card, fmt_duration,
                      label, repolish, section)
from .workers import JobWorker

FINISH_LINES = ["Jackpot. Subtitles embedded.", "Smooth. Every line in place.",
                "Stylish. Subtitles locked and loaded."]


class GlowButton(QPushButton):
    """The big GENERATE button: accent fill and a crimson glow on hover."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setProperty("kind", "accent")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(58)
        self.setFont(theme.display_font(19))
        self.fx = QGraphicsDropShadowEffect(self)
        self.fx.setOffset(0, 0)
        self.fx.setBlurRadius(0)
        self.fx.setColor(QColor(theme.current().accent))
        self.setGraphicsEffect(self.fx)
        self.anim = QVariantAnimation(self, duration=260)
        self.anim.valueChanged.connect(lambda v: self.fx.setBlurRadius(float(v)))

    def _glow(self, on: bool):
        p = theme.current()
        self.fx.setColor(QColor(p.accent))
        self.anim.stop()
        self.anim.setStartValue(self.fx.blurRadius())
        self.anim.setEndValue((34 if p.glow else 14) if on and self.isEnabled() else 0)
        self.anim.start()

    def enterEvent(self, e):
        self._glow(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._glow(False)
        super().leaveEvent(e)


STATUS_ICON = {"waiting": "○", "working": "◆", "done": "✔", "failed": "✕", "cancelled": "–"}


class MainWindow(QMainWindow):
    def __init__(self, settings: config.Settings):
        super().__init__()
        self.s = settings
        self.queue: list[Path] = []
        self.status: dict[int, str] = {}
        self.outputs: dict[int, Path] = {}
        self.worker: JobWorker | None = None
        self.job_index = 0
        self.job_t0 = 0.0
        self.batch_t0 = 0.0
        self.file_progress = 0.0
        self.eta_smooth: float | None = None
        self._finish_idx = 0
        self._loading = True

        self.setWindowTitle("AutoSub9000")
        self.setMinimumSize(1020, 720)
        self.resize(1180, 860)
        if self.s.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(self.s.window_geometry.encode()))

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        bl = QVBoxLayout(body)
        bl.setContentsMargins(26, 22, 26, 18)
        bl.setSpacing(18)

        top = QHBoxLayout()
        top.setSpacing(18)
        left = self._build_input_column()
        left.addWidget(self._build_progress())
        self.progress_card.hide()
        top.addLayout(left, 3)
        top.addWidget(self._build_settings(), 2)
        bl.addLayout(top, 1)
        self.log = LogPanel()
        self.log.toggle.setChecked(self.s.log_open)
        self.log.toggle.toggled.connect(self._log_toggled)
        bl.addWidget(self.log)

        self._timer = QTimer(self, interval=500)
        self._timer.timeout.connect(self._tick)

        self._load_settings()
        self._loading = False
        self._refresh_queue()
        self._update_controls()

    # =========================================================== build: header
    def _build_header(self) -> QWidget:
        h = QFrame()
        h.setObjectName("Header")
        h.setProperty("glow", theme.current().glow)
        self.header = h
        lay = QHBoxLayout(h)
        lay.setContentsMargins(24, 14, 20, 14)
        lay.setSpacing(12)
        icon = label("")
        pm = QPixmap(str(theme.assets_dir() / "autosub9000.svg"))
        if not pm.isNull():
            dpr = self.devicePixelRatioF()
            pm = pm.scaled(int(40 * dpr), int(40 * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            icon.setPixmap(pm)
        lay.addWidget(icon)
        title = label("AUTOSUB")
        title.setFont(theme.deco_font(25))
        lay.addWidget(title)
        nine = label("9000")
        nine.setFont(theme.deco_font(25))
        nine.setStyleSheet(f"color: {theme.current().accent};")
        self.nine = nine
        lay.addWidget(nine)
        lay.addSpacing(10)
        tag = label("SUBTITLES WITH STYLE", "faint")
        tag.setFont(theme.display_font(12))
        lay.addWidget(tag, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)
        self.device_badge = label("Device: auto", "faint")
        lay.addWidget(self.device_badge)
        lay.addSpacing(8)
        self.models_btn = button("Models", "ghost")
        self.models_btn.clicked.connect(self.open_models)
        lay.addWidget(self.models_btn)
        self.theme_btn = button("", "ghost")
        self.theme_btn.setToolTip("Toggle light / dark theme")
        self.theme_btn.clicked.connect(self.toggle_theme)
        lay.addWidget(self.theme_btn)
        return h

    # =========================================================== build: input
    def _build_input_column(self):
        col = QVBoxLayout()
        col.setSpacing(12)
        self.drop = DropZone()
        self.drop.start_dir = self.s.last_open_dir
        self.drop.filesDropped.connect(self.add_files)
        col.addWidget(self.drop, 1)

        self.queue_card = card()
        ql = QVBoxLayout(self.queue_card)
        ql.setContentsMargins(16, 14, 16, 14)
        ql.setSpacing(8)
        qh = QHBoxLayout()
        qh.addWidget(section("Queue"))
        self.queue_count = label("", "faint")
        qh.addWidget(self.queue_count)
        qh.addStretch(1)
        self.q_add = button("Add…", "ghost")
        self.q_remove = button("Remove", "ghost")
        self.q_clear = button("Clear", "ghost")
        for b in (self.q_add, self.q_remove, self.q_clear):
            qh.addWidget(b)
        ql.addLayout(qh)
        self.queue_list = QListWidget()
        self.queue_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.queue_list.setMinimumHeight(90)
        self.queue_list.itemDoubleClicked.connect(self._open_item)
        ql.addWidget(self.queue_list, 1)
        self.q_add.clicked.connect(self.drop.browse)
        self.q_remove.clicked.connect(self._remove_selected)
        self.q_clear.clicked.connect(self._clear_queue)
        col.addWidget(self.queue_card, 2)
        return col

    # =========================================================== build: settings
    def _build_settings(self) -> QWidget:
        c = card()
        c.setMinimumWidth(380)
        v = QVBoxLayout(c)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(8)

        t = label("Settings")
        t.setFont(theme.display_font(20))
        v.addWidget(t)
        v.addSpacing(4)

        v.addWidget(section("Spoken language"))
        self.lang = QComboBox()
        self.lang.addItem("Auto-detect", "auto")
        for code, name in sorted_choices():
            self.lang.addItem(name, code)
        self.lang.setMaxVisibleItems(16)
        v.addWidget(self.lang)
        v.addSpacing(6)

        v.addWidget(section("Model"))
        self.model = QComboBox()
        v.addWidget(self.model)
        self.model_note = label("", "faint", wrap=True)
        v.addWidget(self.model_note)
        v.addSpacing(4)

        self.translate = QCheckBox("Translate to English")
        f = self.translate.font()
        f.setWeight(f.Weight.DemiBold)
        self.translate.setFont(f)
        v.addWidget(self.translate)
        self.tr_box = QWidget()
        tb = QVBoxLayout(self.tr_box)
        tb.setContentsMargins(28, 0, 0, 0)
        tb.setSpacing(6)
        self.keep = QCheckBox("Keep the original-language track too")
        tb.addWidget(self.keep)
        row = QHBoxLayout()
        row.addWidget(label("Translation model", "muted"))
        self.tr_model = QComboBox()
        row.addWidget(self.tr_model, 1)
        tb.addLayout(row)
        self.tr_warn = label("", "warning", wrap=True)
        tb.addWidget(self.tr_warn)
        v.addWidget(self.tr_box)
        v.addSpacing(6)

        v.addWidget(section("Output"))
        orow = QHBoxLayout()
        self.fmt = Segmented([("mkv", "MKV"), ("mp4", "MP4")])
        orow.addWidget(self.fmt)
        orow.addStretch(1)
        self.fmt_note = label("", "faint")
        orow.addWidget(self.fmt_note)
        v.addLayout(orow)
        frow = QHBoxLayout()
        frow.setSpacing(6)
        self.out_btn = button("", "ghost")
        self.out_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.out_btn.setStyleSheet("text-align: left;")
        self.out_btn.setToolTip("Where the new video is saved")
        self.out_btn.clicked.connect(self._choose_out)
        self.out_reset = button("✕", "ghost")
        self.out_reset.setToolTip("Save next to the original video")
        self.out_reset.setFixedWidth(36)
        self.out_reset.clicked.connect(lambda: self._set_out(""))
        frow.addWidget(self.out_btn, 1)
        frow.addWidget(self.out_reset)
        v.addLayout(frow)
        v.addSpacing(4)

        v.addWidget(section("Extras"))
        self.save_srt = QCheckBox("Also save separate .srt files")
        self.burn = QCheckBox("Burn subtitles into the picture (re-encodes, slower)")
        self.review = QCheckBox("Review and edit before embedding")
        for w in (self.save_srt, self.burn, self.review):
            v.addWidget(w)
        v.addSpacing(4)

        drow = QHBoxLayout()
        drow.addWidget(section("Device"))
        drow.addStretch(1)
        self.device = Segmented([("auto", "Auto"), ("gpu", "GPU"), ("cpu", "CPU")])
        drow.addWidget(self.device)
        v.addLayout(drow)

        v.addStretch(1)
        v.addSpacing(10)
        self.go = GlowButton("GENERATE SUBTITLES")
        self.go.clicked.connect(self.start)
        v.addWidget(self.go)
        self.go_hint = label("", "faint", wrap=True)
        self.go_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.go_hint)

        for w in (self.lang, self.model, self.tr_model):
            w.currentIndexChanged.connect(self._changed)
        for w in (self.translate, self.keep, self.save_srt, self.burn, self.review):
            w.toggled.connect(self._changed)
        self.fmt.changed.connect(self._changed)
        self.device.changed.connect(self._changed)
        return c

    # =========================================================== build: progress
    def _build_progress(self) -> QWidget:
        c = card()
        self.progress_card = c
        outer = QVBoxLayout(c)
        outer.setContentsMargins(18, 14, 20, 16)
        outer.setSpacing(10)
        lay = QHBoxLayout()
        lay.setSpacing(16)
        outer.addLayout(lay)
        self.meter = StyleMeter()
        lay.addWidget(self.meter, 0, Qt.AlignmentFlag.AlignVCenter)

        mid = QVBoxLayout()
        mid.setSpacing(6)
        srow = QHBoxLayout()
        self.stage_label = label("READY")
        self.stage_label.setFont(theme.display_font(26))
        srow.addWidget(self.stage_label, 1)
        self.cancel_btn = button("Cancel", "danger")
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.hide()
        srow.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignTop)
        mid.addLayout(srow)
        self.file_label = label("Drop a video to begin.", "muted")
        mid.addWidget(self.file_label)
        mid.addSpacing(4)
        prow = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        prow.addWidget(self.bar, 1)
        self.pct = label("0%")
        self.pct.setFont(theme.display_font(18))
        self.pct.setMinimumWidth(64)
        self.pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prow.addWidget(self.pct)
        mid.addLayout(prow)
        self.times = label("", "faint")
        mid.addWidget(self.times)

        self.banner = QFrame()
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(12, 10, 12, 10)
        self.banner_text = label("", wrap=True)
        self.banner_text.setTextFormat(Qt.TextFormat.RichText)
        bl.addWidget(self.banner_text, 1)
        self.b_open = button("Open folder", "ghost")
        self.b_play = button("Play", "ghost")
        self.b_log = button("Show log", "ghost")
        bl.addWidget(self.b_play)
        bl.addWidget(self.b_open)
        bl.addWidget(self.b_log)
        self.b_open.clicked.connect(self._open_last_folder)
        self.b_play.clicked.connect(self._play_last)
        self.b_log.clicked.connect(lambda: self.log.toggle.setChecked(True))
        self.banner.hide()
        mid.addWidget(self.banner)
        mid.addStretch(1)
        lay.addLayout(mid, 1)

        outer.addWidget(section("Live preview"))
        self.preview = QListWidget()
        self.preview.setMinimumHeight(120)
        self.preview.setMaximumHeight(170)
        self.preview.setWordWrap(True)
        self.preview.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        outer.addWidget(self.preview)
        return c

    # =========================================================== settings sync
    def _fill_model_combo(self, combo: QComboBox, selected: str, for_translation: bool):
        combo.blockSignals(True)
        combo.clear()
        for m in models.CATALOGUE:
            inst = models.is_installed(m.name)
            text = m.name + ("" if inst else "   (not installed)")
            if for_translation and not m.can_translate:
                text += "   ⚠"
            combo.addItem(text, m.name)
            if not inst:
                idx = combo.count() - 1
                combo.setItemData(idx, QColor(theme.current().text_faint), Qt.ItemDataRole.ForegroundRole)
        i = combo.findData(selected)
        combo.setCurrentIndex(i if i >= 0 else 0)
        combo.blockSignals(False)

    def _load_settings(self):
        s = self.s
        i = self.lang.findData(s.source_language)
        self.lang.setCurrentIndex(max(0, i))
        self._fill_model_combo(self.model, s.transcribe_model, False)
        self._fill_model_combo(self.tr_model, s.translate_model, True)
        self.translate.setChecked(s.translate)
        self.keep.setChecked(s.keep_original)
        self.fmt.setValue(s.output_format)
        self.save_srt.setChecked(s.save_srt)
        self.burn.setChecked(s.burn_in)
        self.review.setChecked(s.review)
        self.device.setValue(s.device)
        self._set_out(s.output_dir, save=False)
        self.theme_btn.setText("☀  Light" if s.theme == "dark" else "☾  Dark")

    def _changed(self, *_):
        if self._loading:
            return
        s = self.s
        s.source_language = self.lang.currentData()
        s.transcribe_model = self.model.currentData()
        s.translate_model = self.tr_model.currentData()
        s.translate = self.translate.isChecked()
        s.keep_original = self.keep.isChecked()
        s.output_format = self.fmt.value()
        s.save_srt = self.save_srt.isChecked()
        s.burn_in = self.burn.isChecked()
        s.review = self.review.isChecked()
        s.device = self.device.value()
        s.save()
        self._update_controls()

    def _set_out(self, path: str, save: bool = True):
        self.s.output_dir = path
        if path:
            p = Path(path)
            short = str(p).replace(str(Path.home()), "~", 1)
            self.out_btn.setText(f"📁  {short}")
        else:
            self.out_btn.setText("📁  Same folder as each video")
        self.out_reset.setVisible(bool(path))
        if save:
            self.s.save()

    def _choose_out(self):
        d = QFileDialog.getExistingDirectory(self, "Output folder", self.s.output_dir or self.s.last_open_dir
                                             or str(Path.home()))
        if d:
            self._set_out(d)

    def _update_controls(self):
        running = self.worker is not None and self.worker.isRunning()
        tr = self.translate.isChecked()
        self.tr_box.setVisible(tr)
        keep = self.keep.isChecked()
        tm = self.model.currentData()
        trm = self.tr_model.currentData()

        # the transcription model is unused when translating without keeping the original
        self.model.setEnabled(not running and not (tr and not keep))
        notes = []
        if tr and not keep:
            notes.append("Not used: translation only needs the translation model.")
        elif tm and not models.is_installed(tm):
            notes.append("Not installed – open Models to download it.")
        elif tm:
            info = models.get(tm)
            notes.append(f"{info.speed} · {info.accuracy} accuracy · {info.size_mb:,} MB")
        self.model_note.setText(" ".join(notes))

        warn = translation_model_check(trm) if tr else None
        if tr and trm and not models.is_installed(trm):
            warn = (warn + "  " if warn else "") + f"{trm} isn't installed – open Models to download it."
        self.tr_warn.setText(f"⚠  {warn}" if warn else "")
        self.tr_warn.setVisible(bool(warn))

        self.fmt_note.setText("SRT tracks · plays everywhere" if self.fmt.value() == "mkv"
                              else "mov_text tracks · Apple/TV friendly")

        n_wait = sum(1 for i in range(len(self.queue)) if self.status.get(i, "waiting") == "waiting")
        problems = []
        if not self.queue:
            problems.append("Add a video to get started.")
        elif n_wait == 0 and not running:
            problems.append("Everything in the queue is done – add more videos.")
        needed = []
        if not tr or keep:
            needed.append(tm)
        if tr:
            needed.append(trm)
        missing = [m for m in needed if m and not models.is_installed(m)]
        if missing:
            problems.append(f"Model not installed: {', '.join(missing)}.")
        self.go.setEnabled(not running and not problems)
        if running:
            self.go_hint.setText("Working…")
        else:
            self.go_hint.setText(problems[0] if problems else
                                 f"{n_wait} video{'s' if n_wait != 1 else ''} ready")
        for w in (self.lang, self.tr_model, self.translate, self.keep, self.fmt, self.out_btn,
                  self.out_reset, self.save_srt, self.burn, self.review, self.device,
                  self.q_remove, self.q_clear, self.models_btn):
            w.setEnabled(not running)

    def _log_toggled(self, on: bool):
        self.s.log_open = on
        self.s.save()

    # =========================================================== queue
    def add_files(self, paths: list[Path]):
        added = 0
        new_idx = []
        for p in paths:
            p = Path(p)
            if p.suffix.lower() not in VIDEO_EXTENSIONS or not p.is_file():
                self.log.append(f"skipped (not a supported video): {p}")
                continue
            if p in self.queue and self.status.get(self.queue.index(p)) == "waiting":
                continue
            self.queue.append(p)
            self.status[len(self.queue) - 1] = "waiting"
            new_idx.append(len(self.queue) - 1)
            added += 1
        if paths:
            self.s.last_open_dir = str(Path(paths[0]).parent)
            self.drop.start_dir = self.s.last_open_dir
            self.s.save()
        if new_idx and self.worker and self.worker.isRunning():
            # join the running batch
            self._index_map.extend(new_idx)
            self.worker.files.extend(self.queue[i] for i in new_idx)
        self._refresh_queue()
        self._update_controls()
        if added and not (self.worker and self.worker.isRunning()):
            self.file_label.setText(f"{added} video{'s' if added != 1 else ''} added. Hit GENERATE when ready.")

    def _refresh_queue(self):
        self.queue_list.clear()
        p = theme.current()
        colors = {"waiting": p.text_muted, "working": p.accent_hover, "done": p.success,
                  "failed": p.error, "cancelled": p.text_faint}
        for i, path in enumerate(self.queue):
            st = self.status.get(i, "waiting")
            text = f"{STATUS_ICON[st]}   {path.name}"
            if st == "done" and i in self.outputs:
                text += f"   →  {self.outputs[i].name}"
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, i)
            it.setForeground(QColor(colors[st]) if st != "waiting" else QColor(p.text))
            it.setToolTip(str(path))
            self.queue_list.addItem(it)
        self.queue_card.setVisible(bool(self.queue))
        self.drop.setCompact(bool(self.queue))
        done = sum(1 for s in self.status.values() if s == "done")
        self.queue_count.setText(f"{len(self.queue)} file{'s' if len(self.queue) != 1 else ''}"
                                 + (f" · {done} done" if done else ""))

    def _remove_selected(self):
        rows = sorted({self.queue_list.row(i) for i in self.queue_list.selectedItems()}, reverse=True)
        for r in rows:
            del self.queue[r]
        old = self.status
        self.status = {}
        self.outputs = {}
        kept = [i for i in range(len(old)) if i not in rows]
        for new_i, old_i in enumerate(kept):
            self.status[new_i] = old.get(old_i, "waiting")
        self._refresh_queue()
        self._update_controls()

    def _clear_queue(self):
        self.queue.clear()
        self.status.clear()
        self.outputs.clear()
        self._refresh_queue()
        self._update_controls()

    def _open_item(self, item):
        i = item.data(Qt.ItemDataRole.UserRole)
        if i in self.outputs:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.outputs[i].parent)))

    # =========================================================== run
    def _options(self) -> JobOptions:
        s = self.s
        return JobOptions(input=Path("."), source_language=s.source_language, translate=s.translate,
                          keep_original=s.keep_original, transcribe_model=s.transcribe_model,
                          translate_model=s.translate_model, output_format=s.output_format,
                          output_dir=Path(s.output_dir) if s.output_dir else None,
                          save_srt=s.save_srt, burn_in=s.burn_in, device=s.device)

    def start(self):
        if self.worker and self.worker.isRunning():
            return
        pending = [i for i in range(len(self.queue)) if self.status.get(i) == "waiting"]
        if not pending:
            return
        self._index_map = pending
        files = [self.queue[i] for i in pending]
        self.worker = JobWorker(files, self._options(), self.s.review, self)
        w = self.worker
        w.jobStarted.connect(self._on_job_started)
        w.stage.connect(self._on_stage)
        w.progress.connect(self._on_progress)
        w.segment.connect(self._on_segment)
        w.log.connect(self.log.append)
        w.device.connect(self._on_device)
        w.warning.connect(self._on_warning)
        w.jobFinished.connect(self._on_job_finished)
        w.jobFailed.connect(self._on_job_failed)
        w.reviewRequested.connect(self._on_review)
        w.allDone.connect(self._on_all_done)
        self.batch_t0 = time.monotonic()
        self.banner.hide()
        self.preview.clear()
        self.progress_card.show()
        self.cancel_btn.show()
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Cancel")
        self._failures = []
        self._done_count = 0
        w.start()
        self._timer.start()
        self._update_controls()

    def _qi(self, worker_index: int) -> int:
        """Map worker job index to queue index."""
        return self._index_map[worker_index]

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText("Stopping…")
            self.stage_label.setText("STOPPING…")
            self.worker.cancel()

    def _on_job_started(self, i: int, name: str):
        qi = self._qi(i)
        self.job_index = i
        self.status[qi] = "working"
        self._refresh_queue()
        self.job_t0 = time.monotonic()
        self.file_progress = 0.0
        self.eta_smooth = None
        self.meter.reset()
        total = len(self.worker.files)
        self.file_label.setText(f"{name}" + (f"   ·   file {i + 1} of {total}" if total > 1 else ""))
        self.preview.clear()
        self._tick()

    def _on_stage(self, key: str, text: str):
        self.stage_label.setText(text.upper() + ("…" if key not in ("done",) else ""))

    def _on_progress(self, stage_f: float, overall: float):
        self.file_progress = overall
        self.bar.setValue(int(overall * 1000))
        self.pct.setText(f"{overall * 100:.0f}%")
        self.meter.setProgress(overall if overall < 1 else 1.0)

    def _tick(self):
        if not (self.worker and self.worker.isRunning()):
            return
        el = time.monotonic() - self.job_t0
        f = self.file_progress
        eta_txt = "estimating…"
        if f > 0.03 and el > 3:
            eta = el * (1 - f) / f
            self.eta_smooth = eta if self.eta_smooth is None else self.eta_smooth * 0.8 + eta * 0.2
            eta_txt = fmt_duration(self.eta_smooth)
        txt = f"Elapsed {fmt_duration(el)}   ·   ETA {eta_txt}"
        if len(self.worker.files) > 1:
            txt += f"   ·   batch {fmt_duration(time.monotonic() - self.batch_t0)}"
        self.times.setText(txt)

    def _on_segment(self, track: str, start: float, end: float, text: str):
        tag = "EN  " if track == "English" else ""
        it = QListWidgetItem(f"{format_ts(start, '.')[:8]}   {tag}{text}")
        self.preview.addItem(it)
        if self.preview.count() > 400:
            self.preview.takeItem(0)
        self.preview.scrollToBottom()

    def _on_device(self, dev: str):
        self.device_badge.setText(f"● {dev}")
        self.device_badge.setProperty("role", "success" if dev.startswith("GPU") else "muted")
        repolish(self.device_badge)

    def _on_warning(self, msg: str):
        self.log.append(f"!! {msg}")
        self._show_banner("warning", f"⚠  {msg}", buttons=False)

    def _on_review(self, info, tracks):
        from .editor import SubtitleEditor
        dlg = SubtitleEditor(info.path, tracks, self)
        ok = dlg.exec()
        self.worker.submitReview(dlg.result_tracks() if ok else None)

    def _on_job_finished(self, i: int, res):
        qi = self._qi(i)
        self.status[qi] = "done"
        self._done_count += 1
        if res.output:
            self.outputs[qi] = res.output
        elif res.srt_files:
            self.outputs[qi] = res.srt_files[0]
        self._last_output = self.outputs.get(qi)
        self._refresh_queue()
        self.meter.setProgress(1.0)
        tracks = ", ".join(t.title for t in res.tracks)
        self.log.append(f"✔ {res.input.name}: {tracks} in {res.elapsed:.1f}s on {res.device}")

    def _on_job_failed(self, i: int, msg: str, hint: str, details: str):
        qi = self._qi(i)
        self.status[qi] = "failed"
        self._failures.append((self.queue[qi].name, msg, hint))
        self._refresh_queue()
        self.meter.setFailed()
        self.log.append(f"✕ {self.queue[qi].name}: {msg} {hint}")

    def _on_all_done(self, cancelled: bool):
        self._timer.stop()
        self.cancel_btn.hide()
        for i, st in self.status.items():
            if st == "working":
                self.status[i] = "cancelled" if cancelled else "failed"
        if cancelled:
            for i in self._index_map:
                if self.status.get(i) == "cancelled":
                    self.status[i] = "waiting"  # can be restarted
        self._refresh_queue()
        n_ok = self._done_count
        n_fail = len(self._failures)
        el = time.monotonic() - self.batch_t0
        self.times.setText(f"Total time {fmt_duration(el)}")
        if cancelled:
            self.stage_label.setText("CANCELLED")
            self.meter.setIdle()
            self._show_banner("warning", "Stopped. Nothing was overwritten; partial files were removed.",
                              buttons=False)
        elif n_fail and not n_ok:
            self.stage_label.setText("FAILED")
            name, msg, hint = self._failures[-1]
            self._show_banner("error", f"<b>{msg}</b><br>{hint}" +
                              (f"<br><span style='color:{theme.current().text_faint}'>{name}</span>"),
                              buttons=False, log=True)
            notify("AutoSub9000 – failed", f"{name}: {msg}")
        else:
            line = FINISH_LINES[self._finish_idx % len(FINISH_LINES)]
            self._finish_idx += 1
            self.stage_label.setText("SSS – DONE")
            self.bar.setValue(1000)
            self.pct.setText("100%")
            extra = f"  {n_fail} failed – see the queue." if n_fail else ""
            out = getattr(self, "_last_output", None)
            where = f"<br><span style='color:{theme.current().text_muted}'>{out}</span>" if out else ""
            self._show_banner("success", f"<b>{line}</b>  {n_ok} video{'s' if n_ok != 1 else ''} in "
                              f"{fmt_duration(el)}.{extra}{where}", buttons=bool(out), log=bool(n_fail))
            notify("AutoSub9000 – done", f"{line} {n_ok} video{'s' if n_ok != 1 else ''} finished."
                   + (f" {n_fail} failed." if n_fail else ""))
        self.worker = None
        self._update_controls()

    def _show_banner(self, kind: str, html: str, buttons: bool, log: bool = False):
        self.banner.setProperty("banner", "error" if kind == "error" else "warning" if kind == "warning" else "")
        if kind == "success":
            self.banner.setStyleSheet(f"QFrame {{ border: 1px solid {theme.current().success}; border-radius: 10px; }}"
                                      "QLabel { border: none; }")
        else:
            self.banner.setStyleSheet("QLabel { border: none; background: transparent; }")
        repolish(self.banner)
        self.banner_text.setText(html)
        self.b_open.setVisible(buttons)
        self.b_play.setVisible(buttons)
        self.b_log.setVisible(log)
        self.banner.show()

    def _open_last_folder(self):
        out = getattr(self, "_last_output", None)
        if out:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(out).parent)))

    def _play_last(self):
        out = getattr(self, "_last_output", None)
        if out:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))

    # =========================================================== dialogs
    def open_models(self):
        from .model_manager import ModelManager
        dlg = ModelManager(self)
        dlg.modelsChanged.connect(self._models_changed)
        dlg.exec()
        self._models_changed()

    def _models_changed(self):
        self._loading = True
        self._fill_model_combo(self.model, self.s.transcribe_model, False)
        self._fill_model_combo(self.tr_model, self.s.translate_model, True)
        self._loading = False
        self._update_controls()

    def maybe_first_run(self):
        if self.s.setup_done or models.installed():
            if not self.s.setup_done:
                self.s.setup_done = True
                self.s.save()
            return
        from .setup_wizard import SetupWizard
        SetupWizard(self).exec()
        # the wizard may have changed settings on disk
        fresh = config.Settings.load()
        self.s.setup_done = fresh.setup_done
        self.s.transcribe_model = fresh.transcribe_model
        self.s.translate_model = fresh.translate_model
        self._models_changed()

    def toggle_theme(self):
        from PySide6.QtWidgets import QApplication
        self.s.theme = "light" if self.s.theme == "dark" else "dark"
        self.s.save()
        p = theme.apply(QApplication.instance(), self.s.theme)
        self.theme_btn.setText("☀  Light" if self.s.theme == "dark" else "☾  Dark")
        self.nine.setStyleSheet(f"color: {p.accent};")
        self.header.setProperty("glow", p.glow)
        repolish(self.header)
        self._models_changed()
        self._refresh_queue()
        self.update()
        for w in self.findChildren(QWidget):
            w.update()

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            r = QMessageBox.question(self, "Still working",
                                     "A job is still running. Stop it and quit?")
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.worker.cancel()
            self.worker.wait(8000)
        self.s.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.s.save()
        super().closeEvent(e)

