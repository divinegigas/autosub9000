"""Paths (XDG) and persistent settings."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import APP_ID


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / default


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / APP_ID


def models_dir() -> Path:
    override = os.environ.get("AUTOSUB_MODELS_DIR")
    return Path(override) if override else data_dir() / "models"


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / APP_ID


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / APP_ID


@dataclass
class Settings:
    source_language: str = "auto"
    translate: bool = False
    keep_original: bool = True
    transcribe_model: str = "large-v3-turbo"
    translate_model: str = "large-v3"
    output_format: str = "mkv"  # mkv | mp4
    output_dir: str = ""  # empty = next to the source file
    save_srt: bool = False
    burn_in: bool = False
    review: bool = False  # open the subtitle editor before embedding
    device: str = "auto"  # auto | gpu | cpu
    theme: str = "dark"
    setup_done: bool = False
    last_open_dir: str = ""
    log_open: bool = False
    window_geometry: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def path(cls) -> Path:
        return config_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        try:
            raw = json.loads(cls.path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(p)
