"""Locate bundled helper binaries (ffmpeg, ffprobe, whisper-cli).

Search order:
  1. $AUTOSUB_BIN_DIR (set by the AppImage's AppRun to $APPDIR/usr/bin)
  2. <repo>/vendor/bin (developer builds made by packaging/build-whisper.sh)
  3. $PATH
"""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path

from .errors import MissingBinary

_REPO_VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "bin"

_ALIASES = {
    "whisper-cli": ["whisper-cli", "whisper-cpp", "whisper"],
    "ffmpeg": ["ffmpeg"],
    "ffprobe": ["ffprobe"],
}

_HINTS = {
    "whisper-cli": "Build it with packaging/build-whisper.sh, or use the AppImage which bundles it.",
    "ffmpeg": "Install ffmpeg (sudo dnf install ffmpeg-free) or use the AppImage which bundles it.",
    "ffprobe": "Install ffmpeg (sudo dnf install ffmpeg-free) or use the AppImage which bundles it.",
}


def _search_dirs() -> list[Path]:
    dirs = []
    if os.environ.get("AUTOSUB_BIN_DIR"):
        dirs.append(Path(os.environ["AUTOSUB_BIN_DIR"]))
    dirs.append(_REPO_VENDOR)
    return dirs


@lru_cache(maxsize=None)
def find(name: str) -> str:
    for d in _search_dirs():
        for alias in _ALIASES.get(name, [name]):
            p = d / alias
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
    for alias in _ALIASES.get(name, [name]):
        found = shutil.which(alias)
        if found:
            return found
    raise MissingBinary(f"Can't find the '{name}' program.", _HINTS.get(name, ""))
