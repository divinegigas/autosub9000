"""Design tokens, bundled fonts and the Qt style sheet.

Look: gunmetal black, one blood-crimson accent, gothic display type (Cinzel)
for headings, Inter for everything you actually read. Legibility first:
body text is always a plain sans at comfortable size and contrast.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from ..gui_paths import assets_dir




@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    bg2: str          # header / sunken areas
    surface: str      # cards
    surface2: str     # inputs
    surface3: str     # hover
    border: str
    border_strong: str
    text: str
    text_muted: str
    text_faint: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str  # translucent accent for highlights
    on_accent: str
    success: str
    warning: str
    error: str
    glow: bool


DARK = Palette(
    name="dark",
    bg="#0d0d10", bg2="#09090b", surface="#16161b", surface2="#1e1e25", surface3="#262630",
    border="#2a2a34", border_strong="#3a3a47",
    text="#eeeef1", text_muted="#a3a3b0", text_faint="#6e6e7c",
    accent="#dc2a43", accent_hover="#f0435a", accent_pressed="#a91e31",
    accent_soft="rgba(220, 42, 67, 0.16)", on_accent="#ffffff",
    success="#46c26a", warning="#e8b54a", error="#ff6b6b", glow=True,
)

LIGHT = Palette(
    name="light",
    bg="#f4f2ef", bg2="#e9e6e1", surface="#ffffff", surface2="#f6f4f1", surface3="#ece9e4",
    border="#dcd7d0", border_strong="#c4bdb3",
    text="#17171c", text_muted="#55555f", text_faint="#8a8a94",
    accent="#b3172c", accent_hover="#cc1f36", accent_pressed="#8e1121",
    accent_soft="rgba(179, 23, 44, 0.10)", on_accent="#ffffff",
    success="#1f8a3e", warning="#9a6a00", error="#c62828", glow=False,
)

FONT_BODY = "Inter"
FONT_DISPLAY = "Cinzel"
FONT_DECO = "Cinzel Decorative"
FONT_MONO = "JetBrains Mono"

_current: Palette = DARK


def current() -> Palette:
    return _current


def load_fonts() -> None:
    global FONT_BODY, FONT_DISPLAY, FONT_DECO, FONT_MONO
    fonts = assets_dir() / "fonts"
    families: dict[str, str] = {}
    for f in sorted(fonts.glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid >= 0:
            fams = QFontDatabase.applicationFontFamilies(fid)
            if fams:
                families[f.stem] = fams[0]
    FONT_BODY = families.get("Inter", "Sans Serif")
    FONT_DISPLAY = families.get("Cinzel", "Serif")
    FONT_DECO = families.get("CinzelDecorative-Black", families.get("CinzelDecorative-Bold", FONT_DISPLAY))
    FONT_MONO = families.get("JetBrainsMono", "Monospace")


def display_font(px: int, weight: QFont.Weight = QFont.Weight.Bold) -> QFont:
    f = QFont(FONT_DISPLAY)
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 104)
    return f


def deco_font(px: int) -> QFont:
    f = QFont(FONT_DECO)
    f.setPixelSize(px)
    f.setWeight(QFont.Weight.Black)
    return f


def mono_font(px: int = 12) -> QFont:
    f = QFont(FONT_MONO)
    f.setPixelSize(px)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


def apply(app: QApplication, name: str = "dark") -> Palette:
    global _current
    p = LIGHT if name == "light" else DARK
    _current = p
    app.setStyle("Fusion")
    body = QFont(FONT_BODY)
    body.setPixelSize(14)
    body.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(body)

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(p.bg))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(p.text))
    pal.setColor(QPalette.ColorRole.Base, QColor(p.surface2))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(p.surface))
    pal.setColor(QPalette.ColorRole.Text, QColor(p.text))
    pal.setColor(QPalette.ColorRole.Button, QColor(p.surface2))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(p.text))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(p.accent))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(p.on_accent))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(p.text_faint))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(p.surface3))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(p.text))
    pal.setColor(QPalette.ColorRole.Link, QColor(p.accent_hover))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(p.text_faint))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(p))
    return p


def stylesheet(p: Palette) -> str:
    check_svg = (assets_dir() / "ui" / "check.svg").as_posix()
    chevron_svg = (assets_dir() / "ui" / f"chevron-{p.name}.svg").as_posix()
    return f"""
* {{ outline: none; }}
QWidget {{ color: {p.text}; }}
QMainWindow, QDialog {{ background: {p.bg}; }}
QToolTip {{ background: {p.surface3}; color: {p.text}; border: 1px solid {p.border_strong};
           border-radius: 6px; padding: 6px 8px; }}

/* ---------- typography roles ---------- */
QLabel[role="muted"] {{ color: {p.text_muted}; }}
QLabel[role="faint"] {{ color: {p.text_faint}; font-size: 12px; }}
QLabel[role="section"] {{ color: {p.text_muted}; font-size: 11px; font-weight: 700;
                         letter-spacing: 1.6px; }}
QLabel[role="warning"] {{ color: {p.warning}; background: transparent; }}
QLabel[role="error"] {{ color: {p.error}; }}
QLabel[role="success"] {{ color: {p.success}; }}

/* ---------- surfaces ---------- */
#Header {{ background: {p.bg2}; border-bottom: 1px solid {p.border}; }}
#Header[glow="true"] {{ border-bottom: 1px solid {p.accent_pressed}; }}
QFrame[card="true"] {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 14px; }}
QFrame[banner="error"] {{ background: {p.accent_soft}; border: 1px solid {p.error}; border-radius: 10px; }}
QFrame[banner="warning"] {{ background: transparent; border: 1px solid {p.warning}; border-radius: 10px; }}
QFrame[divider="true"] {{ background: {p.border}; max-height: 1px; min-height: 1px; border: none; }}

/* ---------- buttons ---------- */
QPushButton {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 9px;
              padding: 8px 16px; font-weight: 600; }}
QPushButton:hover {{ background: {p.surface3}; border-color: {p.border_strong}; }}
QPushButton:pressed {{ background: {p.border}; }}
QPushButton:disabled {{ color: {p.text_faint}; background: {p.surface}; border-color: {p.border}; }}
QPushButton[kind="ghost"] {{ background: transparent; border-color: transparent; padding: 7px 12px; }}
QPushButton[kind="ghost"]:hover {{ background: {p.surface2}; border-color: {p.border}; }}
QPushButton[kind="accent"] {{ background: {p.accent}; color: {p.on_accent}; border: 1px solid {p.accent_hover}; }}
QPushButton[kind="accent"]:hover {{ background: {p.accent_hover}; }}
QPushButton[kind="accent"]:pressed {{ background: {p.accent_pressed}; }}
QPushButton[kind="accent"]:disabled {{ background: {p.surface2}; color: {p.text_faint}; border-color: {p.border}; }}
QPushButton[kind="danger"] {{ background: transparent; color: {p.error}; border: 1px solid {p.error}; }}
QPushButton[kind="danger"]:hover {{ background: {p.accent_soft}; }}
QPushButton[kind="seg"] {{ border-radius: 0; padding: 7px 18px; background: {p.surface2}; }}
QPushButton[kind="seg"][pos="first"] {{ border-top-left-radius: 9px; border-bottom-left-radius: 9px; }}
QPushButton[kind="seg"][pos="last"] {{ border-top-right-radius: 9px; border-bottom-right-radius: 9px; }}
QPushButton[kind="seg"]:checked {{ background: {p.accent}; color: {p.on_accent}; border-color: {p.accent}; }}

/* ---------- inputs ---------- */
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: {p.surface2}; border: 1px solid {p.border}; border-radius: 9px;
    padding: 7px 10px; min-height: 20px; selection-background-color: {p.accent}; }}
QComboBox:hover, QLineEdit:hover {{ border-color: {p.border_strong}; }}
QComboBox:focus, QLineEdit:focus {{ border-color: {p.accent}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url("{chevron_svg}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {p.surface2}; border: 1px solid {p.border_strong};
    border-radius: 8px; padding: 4px; selection-background-color: {p.accent}; selection-color: {p.on_accent}; }}
QCheckBox {{ spacing: 10px; padding: 3px 0; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {p.border_strong};
                        background: {p.surface2}; }}
QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; image: url("{check_svg}"); }}
QCheckBox:disabled {{ color: {p.text_faint}; }}

/* ---------- progress ---------- */
QProgressBar {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 7px;
               min-height: 14px; max-height: 14px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ border-radius: 6px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.accent_pressed}, stop:1 {p.accent_hover}); }}
QProgressBar[thin="true"] {{ min-height: 6px; max-height: 6px; border-radius: 3px; border: none; }}
QProgressBar[thin="true"]::chunk {{ border-radius: 3px; }}

/* ---------- lists, tables, text ---------- */
QListWidget, QTableView, QPlainTextEdit, QTextEdit {{
    background: {p.surface2}; border: 1px solid {p.border}; border-radius: 10px; padding: 4px; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QListWidget::item:hover {{ background: {p.surface3}; }}
QTableView {{ gridline-color: {p.border}; selection-background-color: {p.accent_soft};
             selection-color: {p.text}; alternate-background-color: {p.surface}; }}
QHeaderView::section {{ background: {p.surface}; color: {p.text_muted}; border: none;
    border-bottom: 1px solid {p.border}; padding: 8px; font-weight: 700; font-size: 11px; letter-spacing: 1px; }}
QTableCornerButton::section {{ background: {p.surface}; border: none; }}
QPlainTextEdit#Log {{ background: {p.bg2}; color: {p.text_muted}; }}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border_strong}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p.accent}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.border_strong}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {p.text_muted}; padding: 8px 16px; margin-right: 4px;
               border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.accent}; }}
QTabBar::tab:hover {{ color: {p.text}; }}
QSplitter::handle {{ background: transparent; }}
QMenu {{ background: {p.surface2}; border: 1px solid {p.border_strong}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 5px; }}
QMenu::item:selected {{ background: {p.accent}; color: {p.on_accent}; }}
"""
