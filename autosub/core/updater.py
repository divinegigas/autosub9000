"""Manual self-update for the AppImage, from GitHub Releases.

Runs ONLY when the user clicks "Check for updates" (or uses --update).
There is no automatic or background checking.

A release is expected to contain:
    AutoSub9000-<version>-x86_64.AppImage
    AutoSub9000-<version>-x86_64.AppImage.sha256
(.github/workflows/release.yml publishes exactly that.)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import __version__
from .errors import AutoSubError, Cancelled

REPO = "divinegigas/autosub9000"
API_URL = os.environ.get("AUTOSUB_UPDATE_API", f"https://api.github.com/repos/{REPO}/releases/latest")
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
_ASSET_RE = re.compile(r"^AutoSub9000-[\w.+-]+-x86_64\.AppImage$")


@dataclass
class Release:
    version: str
    tag: str
    notes: str
    appimage_url: str
    appimage_name: str
    size: int
    sha256_url: str | None
    page_url: str

    @property
    def is_newer(self) -> bool:
        return parse_version(self.version) > parse_version(__version__)


def parse_version(v: str) -> tuple:
    nums = re.findall(r"\d+", v.split("-")[0].split("+")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def appimage_path() -> Path | None:
    """The AppImage file we are running from, if any."""
    p = os.environ.get("APPIMAGE")
    return Path(p) if p and Path(p).is_file() else None


def _get(url: str, timeout: float = 15):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"AutoSub9000/{__version__}",
        "Accept": "application/vnd.github+json",
    })
    return urllib.request.urlopen(req, timeout=timeout)


def check(timeout: float = 15) -> Release | None:
    """Return the latest release, or None if the project has no releases yet."""
    try:
        with _get(API_URL, timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code == 403:
            raise AutoSubError("GitHub is rate-limiting update checks.",
                               "Try again in an hour.") from e
        raise AutoSubError("The update check failed.", f"GitHub answered HTTP {e.code}.") from e
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise AutoSubError("Can't reach GitHub.",
                           "Check your internet connection and try again.", str(e)) from e
    except ValueError as e:
        raise AutoSubError("The update server sent an unexpected answer.", "", str(e)) from e

    assets = data.get("assets") or []
    app = next((a for a in assets if _ASSET_RE.match(a.get("name", ""))), None)
    if not app:
        return None
    sha = next((a for a in assets if a.get("name") == app["name"] + ".sha256"), None)
    tag = data.get("tag_name") or ""
    return Release(
        version=tag.lstrip("vV") or "0",
        tag=tag,
        notes=(data.get("body") or "").strip(),
        appimage_url=app["browser_download_url"],
        appimage_name=app["name"],
        size=int(app.get("size") or 0),
        sha256_url=sha["browser_download_url"] if sha else None,
        page_url=data.get("html_url") or RELEASES_PAGE,
    )


def install(rel: Release, progress: Callable[[int, int], None] | None = None,
            cancel: Callable[[], bool] | None = None, target: Path | None = None) -> Path:
    """Download the new AppImage, verify it, and atomically replace the running
    one (same path, so menu entries keep working). Returns the path."""
    target = target or appimage_path()
    if target is None:
        raise AutoSubError("Updates can only be installed into the AppImage.",
                           "You're running from source – update with git pull.")
    if not os.access(target.parent, os.W_OK):
        raise AutoSubError("Can't write next to the AppImage.",
                           f"{target.parent} is read-only. Move the AppImage somewhere you own "
                           "(e.g. ~/Applications) and try again.")
    if not rel.sha256_url:
        raise AutoSubError("This release has no checksum file.",
                           "For safety it won't be installed automatically. "
                           f"Download it manually from {rel.page_url}")

    try:
        with _get(rel.sha256_url) as r:
            expected = r.read().decode("utf-8", "replace").split()[0].strip().lower()
    except Exception as e:  # noqa: BLE001
        raise AutoSubError("Couldn't download the checksum.", "Try again later.", str(e)) from e
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise AutoSubError("The release checksum file is invalid.", f"See {rel.page_url}")

    tmp = target.with_name(f".{target.name}.download")
    h = hashlib.sha256()
    done = 0
    try:
        with _get(rel.appimage_url, timeout=30) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or rel.size or 0)
            while True:
                if cancel and cancel():
                    raise Cancelled()
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except Cancelled:
        tmp.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        tmp.unlink(missing_ok=True)
        if getattr(e, "errno", None) == 28:
            raise AutoSubError("The disk is full.", "Free some space and try again.") from e
        raise AutoSubError("The download was interrupted.", "Try again.", str(e)) from e

    if h.hexdigest() != expected:
        tmp.unlink(missing_ok=True)
        raise AutoSubError("The downloaded update is corrupted (checksum mismatch).",
                           "It was deleted and nothing was changed. Try again.",
                           f"expected {expected}, got {h.hexdigest()}")
    os.chmod(tmp, 0o755)
    os.replace(tmp, target)  # the running copy keeps working until restart
    return target
