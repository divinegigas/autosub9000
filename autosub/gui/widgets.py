"""Custom widgets: drop zone, style-rank meter, segmented control, cards, log."""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation,
                            Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QLinearGradient, QPainter,
                           QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from ..core.media import VIDEO_EXTENSIONS
from . import theme


def card(parent=None) -> QFrame:
    f = QFrame(parent)
    f.setProperty("card", True)
    return f


def label(text: str, role: str | None = None, parent=None, wrap: bool = False) -> QLabel:
    lab = QLabel(text, parent)
    if role:
        lab.setProperty("role", role)
    lab.setWordWrap(wrap)
    return lab


def section(text: str) -> QLabel:
    return label(text.upper(), "section")


def button(text: str, kind: str | None = None, parent=None) -> QPushButton:
    b = QPushButton(text, parent)
    if kind:
        b.setProperty("kind", kind)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def repolish(w: QWidget):
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def _color(c: str) -> QColor:
    if c.startswith("rgba"):
        r, g, b, a = [float(x) for x in c[5:-1].split(",")]
        return QColor(int(r), int(g), int(b), int(a * 255))
    return QColor(c)


# ===================================================================== drop zone

class DropZone(QWidget):
    """Big dashed drop target. Click to browse."""

    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._hover = False
        self._drag = False
        self._pulse = 0.0
        self._compact = False
        self.start_dir = ""
        self._anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=220)
        self._anim.valueChanged.connect(self._on_anim)

    def setCompact(self, compact: bool):
        self._compact = compact
        self.setMinimumHeight(92 if compact else 150)
        self.setMaximumHeight(110 if compact else 16777215)
        self.update()

    def _on_anim(self, v):
        self._pulse = float(v)
        self.update()

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pulse)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def enterEvent(self, e):
        self._hover = True
        self._animate(True)

    def leaveEvent(self, e):
        self._hover = False
        if not self._drag:
            self._animate(False)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.browse()

    def browse(self):
        exts = " ".join(f"*{x}" for x in VIDEO_EXTENSIONS)
        files, _ = QFileDialog.getOpenFileNames(self, "Choose videos", self.start_dir,
                                                f"Videos ({exts});;All files (*)")
        if files:
            self.filesDropped.emit([Path(f) for f in files])

    @staticmethod
    def _video_paths(mime) -> list[Path]:
        out = []
        for url in mime.urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.is_dir():
                    out += sorted(x for x in p.iterdir() if x.suffix.lower() in VIDEO_EXTENSIONS)
                elif p.suffix.lower() in VIDEO_EXTENSIONS:
                    out.append(p)
        return out

    def dragEnterEvent(self, e):
        if self._video_paths(e.mimeData()):
            e.acceptProposedAction()
            self._drag = True
            self._animate(True)
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self._drag = False
        self._animate(False)

    def dropEvent(self, e):
        self._drag = False
        self._animate(self._hover)
        paths = self._video_paths(e.mimeData())
        if paths:
            e.acceptProposedAction()
            self.filesDropped.emit(paths)

    def paintEvent(self, e):
        p = theme.current()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        t = self._pulse

        base = QColor(p.surface)
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(base)
        qp.drawRoundedRect(r, 16, 16)
        if t > 0:
            g = QRadialGradient(r.center(), max(r.width(), r.height()) * 0.7)
            c = QColor(p.accent)
            c.setAlphaF(0.16 * t if p.glow else 0.08 * t)
            g.setColorAt(0, c)
            c2 = QColor(p.accent)
            c2.setAlphaF(0)
            g.setColorAt(1, c2)
            qp.setBrush(g)
            qp.drawRoundedRect(r, 16, 16)

        border = QColor(p.border_strong)
        accent = QColor(p.accent)
        mix = QColor(int(border.red() + (accent.red() - border.red()) * t),
                     int(border.green() + (accent.green() - border.green()) * t),
                     int(border.blue() + (accent.blue() - border.blue()) * t))
        pen = QPen(mix, 2, Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([6, 5])
        qp.setPen(pen)
        qp.setBrush(Qt.BrushStyle.NoBrush)
        qp.drawRoundedRect(r.adjusted(6, 6, -6, -6), 12, 12)

        # icon: film frame with a slash
        cx = r.center().x()
        if self._compact:
            icon_c = QPointF(r.left() + 58, r.center().y())
            size = 34
        else:
            icon_c = QPointF(cx, r.center().y() - 34)
            size = 52
        self._paint_icon(qp, icon_c, size, mix, accent)

        title = "DROP MORE VIDEOS" if self._compact else "DROP YOUR VIDEOS HERE"
        qp.setPen(QColor(p.text))
        f = theme.display_font(17 if self._compact else 24, QFont.Weight.Bold)
        qp.setFont(f)
        if self._compact:
            tr = QRectF(r.left() + 96, r.top(), r.width() - 110, r.height() / 2 + 4)
            qp.drawText(tr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, title)
        else:
            tr = QRectF(r.left(), icon_c.y() + size * 0.75, r.width(), 36)
            qp.drawText(tr, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, title)
        sub = "or click to browse  ·  MKV  MP4  AVI  MOV  WEBM  M4V"
        f2 = QFont(theme.FONT_BODY)
        f2.setPixelSize(13)
        qp.setFont(f2)
        qp.setPen(QColor(p.text_muted))
        if self._compact:
            sr = QRectF(r.left() + 96, r.center().y() + 6, r.width() - 110, 24)
            qp.drawText(sr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, sub)
        else:
            sr = QRectF(r.left(), tr.bottom() + 2, r.width(), 24)
            qp.drawText(sr, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, sub)

    @staticmethod
    def _paint_icon(qp: QPainter, c: QPointF, s: float, frame: QColor, accent: QColor):
        w, h = s * 1.3, s
        rect = QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
        qp.setPen(QPen(frame, 2.5))
        qp.setBrush(Qt.BrushStyle.NoBrush)
        qp.drawRoundedRect(rect, 7, 7)
        bar_w = w * 0.62
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(frame)
        qp.drawRoundedRect(QRectF(c.x() - bar_w / 2, rect.bottom() - h * 0.3, bar_w, h * 0.1), 3, 3)
        path = QPainterPath()
        path.moveTo(rect.left() + w * 0.18, rect.bottom() - h * 0.42)
        path.lineTo(rect.right() - w * 0.12, rect.top() - h * 0.12)
        path.lineTo(rect.right() - w * 0.02, rect.top() - h * 0.02)
        path.lineTo(rect.left() + w * 0.28, rect.bottom() - h * 0.34)
        path.closeSubpath()
        qp.setBrush(accent)
        qp.drawPath(path)


# ===================================================================== style meter

RANKS = [
    # threshold, letter, word
    (0.00, "D", "Decent"),
    (0.12, "C", "Cool"),
    (0.28, "B", "Brilliant"),
    (0.46, "A", "Amazing"),
    (0.64, "S", "Stunning"),
    (0.82, "SS", "Spectacular"),
    (1.00, "SSS", "Sublime Style"),
]


def rank_for(progress: float) -> int:
    idx = 0
    for i, (th, _, _) in enumerate(RANKS):
        if progress >= th - 1e-9:
            idx = i
    return idx


class StyleMeter(QWidget):
    """Style-rank letter that climbs D → SSS with overall progress."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(190, 168)
        self._progress = 0.0
        self._rank = 0
        self._pop = 1.0
        self._idle = True
        self._failed = False
        self._pop_anim = QVariantAnimation(self, startValue=1.35, endValue=1.0, duration=380)
        self._pop_anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._pop_anim.valueChanged.connect(self._set_pop)
        self._shimmer = 0.0
        self._timer = QTimer(self, interval=40)
        self._timer.timeout.connect(self._tick)

    def _set_pop(self, v):
        self._pop = float(v)
        self.update()

    def _tick(self):
        self._shimmer = (self._shimmer + 0.025) % 1.0
        self.update()

    def reset(self):
        self._progress, self._rank, self._idle, self._failed = 0.0, 0, False, False
        self._pop = 1.0
        self._timer.start()
        self.update()

    def setIdle(self):
        self._idle = True
        self._timer.stop()
        self.update()

    def setFailed(self):
        self._failed = True
        self._timer.stop()
        self.update()

    def setProgress(self, f: float):
        self._idle = False
        self._progress = max(0.0, min(1.0, f))
        r = rank_for(self._progress)
        if r != self._rank:
            self._rank = r
            self._pop_anim.stop()
            self._pop_anim.start()
            if r == len(RANKS) - 1:
                self._timer.stop()
        self.update()

    def paintEvent(self, e):
        p = theme.current()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        qp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        _, letter, word = RANKS[self._rank]
        if self._failed:
            letter, word = "✕", "Rough run"
        w = self.width()

        # letter
        size = {1: 96, 2: 78, 3: 62}[len(letter)] if not self._failed else 82
        font = theme.deco_font(int(size * self._pop))
        qp.setFont(font)
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(letter)
        base_y = 104
        x = (w - tw) / 2
        path = QPainterPath()
        path.addText(QPointF(x, base_y), font, letter)
        # slant for attitude
        qp.save()
        qp.translate(w / 2, base_y)
        qp.shear(-0.18, 0)
        qp.translate(-w / 2, -base_y)

        if self._idle:
            fill = QColor(p.border_strong)
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(fill)
            qp.drawPath(path)
        else:
            if p.glow and not self._failed:
                for i, a in ((10, 0.07), (6, 0.12), (3, 0.2)):
                    c = QColor(p.accent)
                    c.setAlphaF(a)
                    qp.setPen(QPen(c, i, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                   Qt.PenJoinStyle.RoundJoin))
                    qp.setBrush(Qt.BrushStyle.NoBrush)
                    qp.drawPath(path)
            g = QLinearGradient(0, base_y - size, 0, base_y)
            if self._failed:
                g.setColorAt(0, QColor(p.text_muted))
                g.setColorAt(1, QColor(p.text_faint))
            else:
                top = QColor("#ffe3e7") if p.glow else QColor(p.accent_hover)
                g.setColorAt(0, top)
                g.setColorAt(0.45, QColor(p.accent_hover))
                g.setColorAt(1, QColor(p.accent_pressed))
            qp.setPen(QPen(QColor(p.bg2) if p.glow else QColor("#ffffff"), 1.2))
            qp.setBrush(g)
            qp.drawPath(path)
            # moving shine while working
            if self._timer.isActive() and not self._failed:
                sx = -60 + (w + 120) * self._shimmer
                sg = QLinearGradient(sx - 30, 0, sx + 30, 0)
                c0 = QColor(255, 255, 255, 0)
                c1 = QColor(255, 255, 255, 90 if p.glow else 60)
                sg.setColorAt(0, c0); sg.setColorAt(0.5, c1); sg.setColorAt(1, c0)
                qp.setPen(Qt.PenStyle.NoPen)
                qp.setBrush(sg)
                qp.drawPath(path)
        qp.restore()

        # word
        wf = theme.display_font(15, QFont.Weight.Bold)
        qp.setFont(wf)
        qp.setPen(QColor(p.text_faint if self._idle else (p.text_muted if self._failed else p.text)))
        qp.drawText(QRectF(0, base_y + 8, w, 22), Qt.AlignmentFlag.AlignHCenter,
                    "Style rank" if self._idle else word.upper() + ("!" if self._rank >= 4 and not self._failed else ""))

        # gauge: progress inside the current rank
        if not self._idle and not self._failed:
            lo = RANKS[self._rank][0]
            hi = RANKS[self._rank + 1][0] if self._rank + 1 < len(RANKS) else 1.0
            inner = 1.0 if hi <= lo else (self._progress - lo) / (hi - lo)
            gr = QRectF(30, base_y + 40, w - 60, 5)
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(QColor(p.surface3))
            qp.drawRoundedRect(gr, 2.5, 2.5)
            fg = QLinearGradient(gr.left(), 0, gr.right(), 0)
            fg.setColorAt(0, QColor(p.accent_pressed))
            fg.setColorAt(1, QColor(p.accent_hover))
            qp.setBrush(fg)
            qp.drawRoundedRect(QRectF(gr.left(), gr.top(), gr.width() * max(0.02, min(1, inner)), gr.height()), 2.5, 2.5)


# ===================================================================== segmented

class Segmented(QWidget):
    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for i, (key, text) in enumerate(options):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("kind", "seg")
            b.setProperty("pos", "first" if i == 0 else "last" if i == len(options) - 1 else "mid")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(b)
            lay.addWidget(b)
            self._buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
        lay.addStretch(1)

    def value(self) -> str:
        for k, b in self._buttons.items():
            if b.isChecked():
                return k
        return next(iter(self._buttons))

    def setValue(self, key: str):
        b = self._buttons.get(key) or next(iter(self._buttons.values()))
        b.setChecked(True)


# ===================================================================== log panel

class LogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        top = QHBoxLayout()
        self.toggle = QToolButton()
        self.toggle.setText("  Log")
        self.toggle.setCheckable(True)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setStyleSheet("QToolButton { border: none; background: transparent; font-weight: 600; padding: 2px; }")
        self.toggle.toggled.connect(self._on_toggle)
        top.addWidget(self.toggle)
        top.addStretch(1)
        self.copy_btn = button("Copy", "ghost")
        self.clear_btn = button("Clear", "ghost")
        top.addWidget(self.copy_btn)
        top.addWidget(self.clear_btn)
        lay.addLayout(top)
        self.text = QPlainTextEdit()
        self.text.setObjectName("Log")
        self.text.setReadOnly(True)
        self.text.setFont(theme.mono_font(12))
        self.text.setMaximumBlockCount(20000)
        self.text.setMinimumHeight(150)
        lay.addWidget(self.text)
        self.copy_btn.clicked.connect(self._copy)
        self.clear_btn.clicked.connect(self.text.clear)
        self._on_toggle(False)

    def _copy(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.text.toPlainText())

    def _on_toggle(self, on: bool):
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.text.setVisible(on)
        self.copy_btn.setVisible(on)
        self.clear_btn.setVisible(on)

    def append(self, line: str):
        self.text.appendPlainText(line)


def fmt_duration(seconds: float) -> str:
    if seconds is None or math.isinf(seconds) or seconds < 0:
        return "--:--"
    s = int(round(seconds))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
