"""Asset locations, without importing Qt (usable from the CLI)."""

from __future__ import annotations

import os
from pathlib import Path


def assets_dir() -> Path:
    env = os.environ.get("AUTOSUB_ASSETS_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    return Path(__file__).resolve().parents[1] / "assets"
