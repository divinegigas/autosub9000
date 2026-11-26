"""Subtitle review/editor: edit text and timings, merge/split, preview video."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDoubleSpinBox, QHBoxLayout,
                               QHeaderView, QLabel, QSplitter, QTabBar, QTableView,
                               QVBoxLayout, QWidget)

from ..core.subtitles import Segment, SubtitleTrack, format_ts, merge, parse_ts, split
from . import theme
from .widgets import button, label

try:  # QtMultimedia ships in the AppImage; degrade gracefully if missing
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
    HAVE_MM = True
except Exception:  # noqa: BLE001
    HAVE_MM = False


class SegmentModel(QAbstractTableModel):
    HEAD = ["#", "START", "END", "TEXT"]
    edited = Signal()

    def __init__(self, segments: list[Segment]):
        super().__init__()
        self.segs = [s.copy() for s in segments]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.segs)

    def columnCount(self, parent=QModelIndex()):
        return 4

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEAD[section]
        return None

    def data(self, idx, role=Qt.ItemDataRole.DisplayRole):
        if not idx.isValid():
            return None
        s = self.segs[idx.row()]
        c = idx.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return [str(idx.row() + 1), format_ts(s.start, "."), format_ts(s.end, "."), s.text][c]
        if role == Qt.ItemDataRole.TextAlignmentRole and c < 3:
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.FontRole and c in (1, 2):
            return theme.mono_font(13)
        if role == Qt.ItemDataRole.ForegroundRole and c == 0:
            from PySide6.QtGui import QColor
            return QColor(theme.current().text_faint)
        if role == Qt.ItemDataRole.ToolTipRole and c in (1, 2):
            return "Format: HH:MM:SS.mmm (or seconds)"
        return None

    def flags(self, idx):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if idx.column() > 0:
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    def setData(self, idx, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole:
            return False
        s = self.segs[idx.row()]
        c = idx.column()
        try:
            if c == 1:
                s.start = max(0.0, parse_ts(str(value)))
                s.end = max(s.end, s.start + 0.05)
            elif c == 2:
                s.end = max(s.start + 0.05, parse_ts(str(value)))
            elif c == 3:
                s.text = str(value)
            else:
                return False
        except ValueError:
            return False
        self.dataChanged.emit(self.index(idx.row(), 0), self.index(idx.row(), 3))
        self.edited.emit()
        return True

    def replace(self, segs: list[Segment]):
        self.beginResetModel()
        self.segs = segs
        self.endResetModel()
        self.edited.emit()


class SubtitleEditor(QDialog):
    def __init__(self, video_path, tracks: list[SubtitleTrack], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review subtitles – AutoSub9000")
        self.resize(1280, 780)
        self.tracks = [SubtitleTrack(t.language, [s.copy() for s in t.segments], t.translated) for t in tracks]
        self.models = [SegmentModel(t.segments) for t in self.tracks]
        self._stop_at: float | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        head = QHBoxLayout()
        t = label("Review")
        t.setFont(theme.display_font(26))
        head.addWidget(t)
        head.addSpacing(16)
        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        for tr in self.tracks:
            self.tabs.addTab(tr.title)
        self.tabs.currentChanged.connect(self._switch)
        head.addWidget(self.tabs)
        head.addStretch(1)
        self.count = label("", "muted")
        head.addWidget(self.count)
        root.addLayout(head)

        split_ = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split_, 1)

        # ----- left: table + tools
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.b_play = button("▶  Play line")
        self.b_merge = button("Merge")
        self.b_split = button("Split")
        self.b_add = button("Insert")
        self.b_del = button("Delete", "danger")
        for b in (self.b_play, self.b_merge, self.b_split, self.b_add, self.b_del):
            tools.addWidget(b)
        tools.addStretch(1)
        tools.addWidget(label("Shift all", "muted"))
        self.shift = QDoubleSpinBox()
        self.shift.setRange(-600, 600)
        self.shift.setDecimals(2)
        self.shift.setSingleStep(0.1)
        self.shift.setSuffix(" s")
        tools.addWidget(self.shift)
        self.b_shift = button("Apply", "ghost")
        tools.addWidget(self.b_shift)
        ll.addLayout(tools)

        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked |
                                   QAbstractItemView.EditTrigger.EditKeyPressed |
                                   QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.table.verticalHeader().hide()
        self.table.setWordWrap(True)
        self.table.setShowGrid(False)
        ll.addWidget(self.table, 1)
        hint = label("Double-click to edit  ·  Ctrl+M merge  ·  Ctrl+K split  ·  Space play line  ·  Del delete",
                     "faint")
        ll.addWidget(hint)
        split_.addWidget(left)

        # ----- right: preview
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 0, 0, 0)
        rl.setSpacing(8)
        if HAVE_MM:
            self.video = QVideoWidget()
            self.video.setMinimumSize(420, 236)
            self.video.setStyleSheet("background: #000; border-radius: 10px;")
            rl.addWidget(self.video, 1)
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(self.video)
            self.player.setSource(QUrl.fromLocalFile(str(video_path)))
            self.player.positionChanged.connect(self._on_pos)
            self.player.errorOccurred.connect(lambda *_: self.overlay.setText(
                "Preview unavailable for this file: " + self.player.errorString()))
        else:
            self.player = None
            rl.addWidget(label("Video preview isn't available in this build.", "muted"), 1)
        self.overlay = QLabel("")
        self.overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay.setWordWrap(True)
        self.overlay.setMinimumHeight(64)
        f = self.overlay.font()
        f.setPixelSize(17)
        f.setWeight(f.Weight.DemiBold)
        self.overlay.setFont(f)
        self.overlay.setStyleSheet(
            f"background: {theme.current().bg2}; border: 1px solid {theme.current().border}; "
            "border-radius: 10px; padding: 10px;")
        rl.addWidget(self.overlay)
        pc = QHBoxLayout()
        self.b_pause = button("Pause", "ghost")
        self.b_pause.clicked.connect(self._toggle_pause)
        self.pos_label = label("00:00:00.000", "muted")
        self.pos_label.setFont(theme.mono_font(13))
        pc.addWidget(self.b_pause)
        pc.addStretch(1)
        pc.addWidget(self.pos_label)
        rl.addLayout(pc)
        split_.addWidget(right)
        split_.setStretchFactor(0, 3)
        split_.setStretchFactor(1, 2)

        # ----- bottom
        bottom = QHBoxLayout()
        self.b_cancel = button("Cancel job", "ghost")
        bottom.addWidget(self.b_cancel)
        bottom.addStretch(1)
        self.b_ok = button("EMBED SUBTITLES", "accent")
        self.b_ok.setMinimumWidth(220)
        self.b_ok.setMinimumHeight(42)
        self.b_ok.setFont(theme.display_font(15))
        bottom.addWidget(self.b_ok)
        root.addLayout(bottom)

        self.b_ok.clicked.connect(self.accept)
        self.b_cancel.clicked.connect(self.reject)
        self.b_play.clicked.connect(self.play_current)
        self.b_merge.clicked.connect(self.do_merge)
        self.b_split.clicked.connect(self.do_split)
        self.b_del.clicked.connect(self.do_delete)
        self.b_add.clicked.connect(self.do_insert)
        self.b_shift.clicked.connect(self.do_shift)
        QShortcut(QKeySequence("Ctrl+M"), self, self.do_merge)
        QShortcut(QKeySequence("Ctrl+K"), self, self.do_split)
        QShortcut(QKeySequence("Space"), self.table, self.play_current)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), self.table, self.do_delete)

        self._switch(0)

    # ------------------------------------------------------------------ helpers
    @property
    def model(self) -> SegmentModel:
        return self.models[self.tabs.currentIndex()]

    def _switch(self, i: int):
        if i < 0:
            return
        self.table.setModel(self.models[i])
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 48)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 120)
        self.table.selectionModel().currentRowChanged.connect(self._row_changed)
        if not getattr(self.models[i], "_hooked", False):
            self.models[i].edited.connect(self._update_count)
            self.models[i]._hooked = True
        self._update_count()
        self.table.resizeRowsToContents()

    def _update_count(self):
        m = self.model
        n = len(m.segs)
        dur = m.segs[-1].end if m.segs else 0
        self.count.setText(f"{n} lines  ·  {format_ts(dur, '.')[:8]}")

    def _rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectionModel().selectedRows()}) or \
            ([self.table.currentIndex().row()] if self.table.currentIndex().isValid() else [])

    def _select(self, row: int):
        if 0 <= row < len(self.model.segs):
            self.table.selectRow(row)
            self.table.scrollTo(self.model.index(row, 0))

    def _row_changed(self, cur, _prev):
        if cur.isValid():
            s = self.model.segs[cur.row()]
            self.overlay.setText(s.text)
            if self.player:
                self.player.pause()
                self.player.setPosition(int(s.start * 1000))

    # ------------------------------------------------------------------ preview
    def play_current(self):
        rows = self._rows()
        if not rows or not self.player:
            return
        s = self.model.segs[rows[0]]
        self._stop_at = s.end
        self.player.setPosition(int(s.start * 1000))
        self.player.play()
        self.b_pause.setText("Pause")

    def _toggle_pause(self):
        if not self.player:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.b_pause.setText("Play")
        else:
            self._stop_at = None
            self.player.play()
            self.b_pause.setText("Pause")

    def _on_pos(self, ms: int):
        t = ms / 1000
        self.pos_label.setText(format_ts(t, "."))
        cur = next((s for s in self.model.segs if s.start <= t < s.end), None)
        self.overlay.setText(cur.text if cur else "")
        if self._stop_at is not None and t >= self._stop_at:
            self._stop_at = None
            self.player.pause()
            self.b_pause.setText("Play")

    # ------------------------------------------------------------------ edits
    def do_merge(self):
        rows = self._rows()
        if len(rows) < 2:
            rows = rows + [rows[0] + 1] if rows else []
        if len(rows) < 2 or rows[-1] >= len(self.model.segs):
            return
        self.model.replace(merge(self.model.segs, rows[0], rows[-1]))
        self._select(rows[0])
        self.table.resizeRowsToContents()

    def do_split(self):
        rows = self._rows()
        if not rows:
            return
        self.model.replace(split(self.model.segs, rows[0]))
        self._select(rows[0])
        self.table.resizeRowsToContents()

    def do_delete(self):
        rows = self._rows()
        if not rows:
            return
        segs = [s for i, s in enumerate(self.model.segs) if i not in set(rows)]
        self.model.replace(segs)
        self._select(min(rows[0], len(segs) - 1))

    def do_insert(self):
        rows = self._rows()
        segs = self.model.segs
        i = rows[-1] + 1 if rows else len(segs)
        start = segs[i - 1].end if i > 0 and segs else 0.0
        end = segs[i].start if i < len(segs) else start + 2.0
        if end - start < 0.5:
            end = start + 2.0
        self.model.replace(segs[:i] + [Segment(start, end, "New line")] + segs[i:])
        self._select(i)
        self.table.edit(self.model.index(i, 3))

    def do_shift(self):
        d = self.shift.value()
        if not d:
            return
        segs = [Segment(max(0.0, s.start + d), max(0.05, s.end + d), s.text) for s in self.model.segs]
        self.model.replace(segs)

    # ------------------------------------------------------------------ result
    def result_tracks(self) -> list[SubtitleTrack]:
        out = []
        for t, m in zip(self.tracks, self.models):
            t.segments = sorted((s for s in m.segs if s.text.strip()), key=lambda s: s.start)
            out.append(t)
        return out

    def done(self, r):
        if self.player:
            self.player.stop()
            QTimer.singleShot(0, lambda: None)
        super().done(r)
