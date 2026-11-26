"""Whisper model catalogue, download (resumable, checksum-verified) and removal.

This module contains the ONLY network code in AutoSub9000. It runs only when
the user explicitly asks to download a model (setup wizard / model manager /
`--download-model`) or opens the model manager, which does one quick
background reachability check.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import config
from .errors import AutoSubError, Cancelled

BASE_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
CHECK_HOST = "huggingface.co"


@dataclass(frozen=True)
class ModelInfo:
    name: str
    filename: str
    size_mb: int
    sha1: str
    speed: str
    accuracy: str
    vram: str
    notes: str
    can_translate: bool = True

    @property
    def url(self) -> str:
        return BASE_URL + self.filename


# SHA-1 checksums from whisper.cpp's models/README.md (v1.8.2).
CATALOGUE: list[ModelInfo] = [
    ModelInfo("tiny", "ggml-tiny.bin", 75, "bd577a113a864445d4c299885e0cb97d4ba92b5f",
              "Fastest", "Low", "~0.4 GB", "Quick drafts and testing."),
    ModelInfo("base", "ggml-base.bin", 142, "465707469ff3a37a2b9b8d8f89f2f99de7299dac",
              "Very fast", "Fair", "~0.5 GB", "Clear speech, single speaker."),
    ModelInfo("small", "ggml-small.bin", 466, "55356645c2b361a969dfd0ef2c5a50d530afd8d5",
              "Fast", "Good", "~1 GB", "Solid all-rounder on slower machines."),
    ModelInfo("medium", "ggml-medium.bin", 1500, "fd9727b6e1217c2f614f9b698455c4ffd82463b4",
              "Moderate", "Very good", "~2.5 GB", "Good translation quality at half the size of large-v3."),
    ModelInfo("large-v3", "ggml-large-v3.bin", 2950, "ad82bf6a9043ceed055076d0fd39f5f186ff8062",
              "Slow", "Best", "~4.5 GB", "Highest accuracy. Recommended for translation."),
    ModelInfo("large-v3-turbo", "ggml-large-v3-turbo.bin", 1550, "4af2b29d7ec73d781377bfd1758ca957a807e941",
              "Fast", "Excellent", "~2.5 GB",
              "Near large-v3 accuracy, several times faster. Not reliable for translation.",
              can_translate=False),
]

BY_NAME = {m.name: m for m in CATALOGUE}
DEFAULT_TRANSCRIBE = "large-v3-turbo"
DEFAULT_TRANSLATE = "large-v3"
TRANSLATE_FALLBACKS = ["large-v3", "medium", "large-v2", "small", "base", "tiny"]


def get(name: str) -> ModelInfo:
    if name not in BY_NAME:
        raise AutoSubError(f"Unknown model “{name}”.",
                           "Choose one of: " + ", ".join(BY_NAME))
    return BY_NAME[name]


def path_for(name: str) -> Path:
    return config.models_dir() / get(name).filename


def is_installed(name: str) -> bool:
    try:
        return path_for(name).is_file()
    except AutoSubError:
        return False


def installed() -> list[str]:
    return [m.name for m in CATALOGUE if is_installed(m.name)]


def best_translate_model() -> str | None:
    for name in TRANSLATE_FALLBACKS:
        if name in BY_NAME and is_installed(name):
            return name
    return None


def delete(name: str) -> None:
    p = path_for(name)
    p.unlink(missing_ok=True)
    p.with_suffix(p.suffix + ".part").unlink(missing_ok=True)


def sha1_of(path: Path, progress: Callable[[float], None] | None = None,
            cancel: Callable[[], bool] | None = None) -> str:
    h = hashlib.sha1()
    total = max(1, path.stat().st_size)
    done = 0
    with open(path, "rb") as f:
        while chunk := f.read(4 << 20):
            if cancel and cancel():
                raise Cancelled()
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done / total)
    return h.hexdigest()


def is_online(timeout: float = 2.5) -> bool:
    """Cheap reachability check. Never called at startup."""
    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    try:
        if proxy:
            req = urllib.request.Request(BASE_URL + "README.md", method="HEAD")
            urllib.request.urlopen(req, timeout=timeout).close()
        else:
            socket.create_connection((CHECK_HOST, 443), timeout=timeout).close()
        return True
    except Exception:
        return False


ProgressCb = Callable[[int, int, str], None]  # (done_bytes, total_bytes, phase)


def download(name: str, progress: ProgressCb | None = None,
             cancel: Callable[[], bool] | None = None, timeout: float = 30) -> Path:
    """Download a model with resume support, then verify its SHA-1.
    phase is "download" or "verify"."""
    info = get(name)
    dest = path_for(name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0

    free = shutil.disk_usage(dest.parent).free
    if free < info.size_mb * 1024 * 1024 * 1.05 - have:
        raise AutoSubError("Not enough disk space for this model.",
                           f"{info.name} needs about {info.size_mb} MB; "
                           f"only {free // (1024 * 1024)} MB free in {dest.parent}.")

    req = urllib.request.Request(info.url, headers={"User-Agent": "AutoSub9000"})
    if have:
        req.add_header("Range", f"bytes={have}-")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 416:  # already complete
            resp = None
        else:
            raise AutoSubError("The model download failed.", f"Server answered HTTP {e.code}.") from e
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise AutoSubError("Can't reach the model server.",
                           "Check your internet connection and try again.", str(e)) from e

    if resp is not None:
        with resp:
            if have and resp.status != 206:  # server ignored Range: start over
                have = 0
            length = int(resp.headers.get("Content-Length") or 0)
            total = have + length if length else info.size_mb * 1024 * 1024
            mode = "ab" if have else "wb"
            done = have
            try:
                with open(part, mode) as f:
                    while True:
                        if cancel and cancel():
                            raise Cancelled()
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total, "download")
            except (socket.timeout, OSError) as e:
                if isinstance(e, Cancelled):
                    raise
                raise AutoSubError("The download was interrupted.",
                                   "Try again – it will resume where it stopped.", str(e)) from e
            if length and done < total:
                raise AutoSubError("The download was interrupted.",
                                   "Try again – it will resume where it stopped.")

    size = part.stat().st_size
    digest = sha1_of(part, (lambda f: progress(int(f * size), size, "verify")) if progress else None, cancel)
    if digest != info.sha1:
        part.unlink(missing_ok=True)
        raise AutoSubError("The downloaded model is corrupted (checksum mismatch).",
                           "It has been deleted. Please download it again.",
                           f"expected {info.sha1}, got {digest}")
    part.replace(dest)
    return dest


def import_file(name: str, src: Path, progress: Callable[[float], None] | None = None) -> Path:
    """Install a model file the user already has (offline install). Verified by checksum."""
    info = get(name)
    src = Path(src)
    digest = sha1_of(src, progress)
    if digest != info.sha1:
        raise AutoSubError(f"That file isn't the official {info.name} model.",
                           f"Expected a file named {info.filename} with a matching checksum.")
    dest = path_for(name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".importing")
    shutil.copyfile(src, tmp)
    tmp.replace(dest)
    return dest
