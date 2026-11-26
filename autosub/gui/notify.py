"""Desktop notifications via the freedesktop notification service (KDE/GNOME).

Uses notify-send or gdbus (both standard on Fedora); falls back to a tray
balloon. Never blocks the GUI."""

from __future__ import annotations

import shutil
import subprocess

from . import theme


def notify(summary: str, body: str = "", tray=None) -> None:
    icon = theme.assets_dir() / "autosub9000.png"
    icon_arg = str(icon) if icon.exists() else "video-x-generic"
    try:
        if shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "--app-name=AutoSub9000", f"--icon={icon_arg}",
                              summary, body], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        if shutil.which("gdbus"):
            subprocess.Popen(["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
                              "--object-path", "/org/freedesktop/Notifications",
                              "--method", "org.freedesktop.Notifications.Notify",
                              "AutoSub9000", "0", icon_arg, summary, body, "[]", "{}", "6000"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    except OSError:
        pass
    if tray is not None:
        try:
            tray.showMessage(summary, body)
        except Exception:  # noqa: BLE001
            pass
