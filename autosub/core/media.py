"""ffprobe wrapper and audio extraction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import binaries
from .errors import AutoSubError
from .process import CancelToken, run

VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v")


@dataclass
class MediaInfo:
    path: Path
    duration: float
    video_streams: list[dict] = field(default_factory=list)
    audio_streams: list[dict] = field(default_factory=list)
    subtitle_streams: list[dict] = field(default_factory=list)
    format_name: str = ""


def probe(path: Path, log: Callable[[str], None] | None = None) -> MediaInfo:
    path = Path(path)
    if not path.is_file():
        raise AutoSubError(f"File not found: {path.name}", str(path))
    code, out, err = run([binaries.find("ffprobe"), "-v", "error", "-show_streams",
                          "-show_format", "-of", "json", str(path)], log=log)
    if code != 0:
        raise AutoSubError(f"“{path.name}” isn't a video file ffmpeg can read.",
                           "It may be damaged or in an unsupported format.", "\n".join(err))
    data = json.loads("\n".join(out) or "{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or 0)
    if not duration:
        duration = max((float(s.get("duration") or 0) for s in streams), default=0.0)
    info = MediaInfo(
        path=path,
        duration=duration,
        video_streams=[s for s in streams if s.get("codec_type") == "video"
                       and not (s.get("disposition") or {}).get("attached_pic")],
        audio_streams=[s for s in streams if s.get("codec_type") == "audio"],
        subtitle_streams=[s for s in streams if s.get("codec_type") == "subtitle"],
        format_name=fmt.get("format_name", ""),
    )
    if not info.audio_streams:
        raise AutoSubError(f"“{path.name}” has no audio track.", "There's nothing to transcribe.")
    return info


_TIME_RE = re.compile(r"out_time_(?:ms|us)=(\d+)")


def extract_audio(info: MediaInfo, wav_path: Path, *, audio_track: int = 0,
                  cancel: CancelToken | None = None,
                  progress: Callable[[float], None] | None = None,
                  log: Callable[[str], None] | None = None) -> Path:
    """Decode one audio track to 16 kHz mono 16-bit WAV (what whisper.cpp wants)."""
    track = min(max(audio_track, 0), len(info.audio_streams) - 1)
    cmd = [binaries.find("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(info.path), "-map", f"0:a:{track}", "-vn", "-sn", "-dn",
           "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
           "-progress", "pipe:1", "-nostats", str(wav_path)]

    def on_out(line: str):
        m = _TIME_RE.match(line)
        if m and progress and info.duration > 0:
            progress(min(1.0, int(m.group(1)) / 1e6 / info.duration))

    code, _, err = run(cmd, cancel=cancel, on_stdout=on_out, on_stderr=log, log=log)
    if code != 0 or not wav_path.exists():
        raise AutoSubError("Couldn't extract the audio from this video.",
                           "The audio track may be damaged or use an unsupported codec.",
                           "\n".join(err[-20:]))
    if progress:
        progress(1.0)
    return wav_path
