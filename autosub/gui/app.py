"""QApplication setup."""

from __future__ import annotations

import os
import sys


def run_gui(files: list[str] | None = None) -> int:
    # Wayland first (KDE), X11 fallback – Qt picks automatically; only nudge
    # the scale-factor rounding so fractional scaling looks crisp.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtWidgets import QApplication

    from .. import APP_NAME, APP_ID, __version__, config
    from . import theme

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)
    icon = theme.assets_dir() / "autosub9000.svg"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    theme.load_fonts()
    settings = config.Settings.load()
    theme.apply(app, settings.theme)

    from .main_window import MainWindow
    win = MainWindow(settings)
    win.show()
    if files:
        from pathlib import Path
        QTimer.singleShot(0, lambda: win.add_files([Path(f) for f in files]))
    QTimer.singleShot(150, win.maybe_first_run)
    return app.exec()
