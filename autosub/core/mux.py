"""Embed subtitle tracks into a copy of the video with ffmpeg.

* Stream copy (-c copy): video and audio are never re-encoded...
* ...unless burn-in is requested, which needs to re-encode the video (H.264).
* MKV gets SRT (subrip) tracks; MP4 gets mov_text tracks.
* Each new track gets an ISO 639-2 language tag and a title, and the English
  track (or the first one) is marked default.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import binaries
from .errors import AutoSubError
from .languages import iso639_2
from .media import MediaInfo
from .process import CancelToken, run
from .subtitles import SubtitleTrack, write_srt


@dataclass
class EmbedTrack:
    track: SubtitleTrack
    srt_path: Path


def output_path_for(src: Path, out_dir: Path | None, fmt: str, suffix: str = ".subbed") -> Path:
    src = Path(src)
    out_dir = Path(out_dir) if out_dir else src.parent
    base = out_dir / f"{src.stem}{suffix}.{fmt}"
    candidate, n = base, 2
    while candidate.exists() or candidate.resolve() == src.resolve():
        candidate = out_dir / f"{src.stem}{suffix} ({n}).{fmt}"
        n += 1
    return candidate


def _filter_escape(path: str) -> str:
    """Escape a path for use inside an ffmpeg filter argument."""
    return path.replace("\\", "\\\\\\\\").replace(":", "\\\\:").replace("'", "\\\\\\'")


_TIME_RE = re.compile(r"out_time_(?:ms|us)=(\d+)")


def embed(info: MediaInfo, tracks: list[EmbedTrack], out_path: Path, *,
          fmt: str = "mkv", burn: EmbedTrack | None = None,
          fonts_dir: Path | None = None,
          cancel: CancelToken | None = None,
          progress: Callable[[float], None] | None = None,
          log: Callable[[str], None] | None = None) -> Path:
    if not tracks:
        raise AutoSubError("No subtitles to embed.", "Whisper didn't find any speech in this file.")
    src = info.path.resolve()
    out_path = Path(out_path)
    if out_path.resolve() == src:
        raise AutoSubError("Refusing to overwrite the original video.", "Choose another output name.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not os.access(out_path.parent, os.W_OK):
        raise AutoSubError("Can't write to the output folder.",
                           f"{out_path.parent} is read-only. Choose another output folder.")

    tmp_out = out_path.with_name(f".{out_path.stem}.partial{out_path.suffix}")
    cmd = [binaries.find("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(src)]
    for t in tracks:
        cmd += ["-f", "srt", "-sub_charenc", "UTF-8", "-i", str(t.srt_path)]

    existing_subs = 0
    if fmt == "mkv":
        cmd += ["-map", "0:v?", "-map", "0:a?", "-map", "0:s?", "-map", "0:t?"]
        existing_subs = len(info.subtitle_streams)
    elif fmt == "mp4":
        cmd += ["-map", "0:v?", "-map", "0:a?"]
    else:
        raise AutoSubError(f"Unknown output format: {fmt}")
    if burn is not None:
        # Filters only work on a single video stream: keep the main one only.
        idx = cmd.index("0:v?")
        cmd[idx] = "0:v:0"
    for i in range(len(tracks)):
        cmd += ["-map", f"{i + 1}:0"]

    if burn is not None:
        style = "FontName=Inter,FontSize=22,Outline=2,Shadow=1,MarginV=28"
        vf = f"subtitles=filename='{_filter_escape(str(burn.srt_path))}'"
        if fonts_dir and Path(fonts_dir).is_dir():
            vf += f":fontsdir='{_filter_escape(str(fonts_dir))}'"
        vf += f":force_style='{style}'"
        cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-c:a", "copy"]
    else:
        cmd += ["-c:v", "copy", "-c:a", "copy"]

    if fmt == "mkv":
        cmd += ["-c:s", "copy"]
        for i in range(len(tracks)):
            cmd += [f"-c:s:{existing_subs + i}", "srt"]
    else:
        cmd += ["-c:s", "mov_text", "-movflags", "+faststart"]

    default_idx = next((i for i, t in enumerate(tracks) if t.track.language == "en"), 0)
    for k in range(existing_subs):
        cmd += [f"-disposition:s:{k}", "0"]
    for i, t in enumerate(tracks):
        s = existing_subs + i
        cmd += [f"-metadata:s:s:{s}", f"language={iso639_2(t.track.language)}",
                f"-metadata:s:s:{s}", f"title={t.track.title}",
                f"-disposition:s:{s}", "default" if i == default_idx else "0"]
        if fmt == "mp4":  # MP4 players read the track name from the handler
            cmd += [f"-metadata:s:s:{s}", f"handler_name={t.track.title}"]

    cmd += ["-progress", "pipe:1", "-nostats", "-f", "matroska" if fmt == "mkv" else "mp4",
            str(tmp_out)]

    def on_out(line: str):
        m = _TIME_RE.match(line)
        if m and progress and info.duration > 0:
            progress(min(0.99, int(m.group(1)) / 1e6 / info.duration))

    try:
        code, _, err = run(cmd, cancel=cancel, on_stdout=on_out, on_stderr=log, log=log)
    except BaseException:
        tmp_out.unlink(missing_ok=True)
        raise
    if code != 0:
        tmp_out.unlink(missing_ok=True)
        tail = "\n".join(err[-20:])
        if fmt == "mp4" and ("codec not currently supported" in tail.lower()
                             or "could not find tag for codec" in tail.lower()):
            raise AutoSubError("This video's audio or video codec can't go into an MP4 file.",
                               "Choose MKV as the output format – it accepts everything.", tail)
        if "No space left" in tail:
            raise AutoSubError("The disk is full.", "Free some space or choose another output folder.", tail)
        raise AutoSubError("Embedding the subtitles failed.", "Open the log panel for details.", tail)
    tmp_out.replace(out_path)
    if progress:
        progress(1.0)
    return out_path


def save_sidecar_srts(tracks: list[SubtitleTrack], video_out: Path, out_dir: Path | None = None) -> list[Path]:
    """Save tracks as <video>.<lang>.srt next to the output video."""
    video_out = Path(video_out)
    out_dir = Path(out_dir) if out_dir else video_out.parent
    paths = []
    for t in tracks:
        p = out_dir / f"{video_out.stem}.{t.language}{'.translated' if t.translated and t.language == 'en' and len(tracks) > 1 else ''}.srt"
        write_srt(t.segments, p)
        paths.append(p)
    return paths


def bundled_fonts_dir() -> Path | None:
    """Bundled fonts directory, used by libass for burn-in (offline, deterministic)."""
    here = Path(__file__).resolve().parents[2] / "assets" / "fonts"
    env = os.environ.get("AUTOSUB_FONTS_DIR")
    for d in ([Path(env)] if env else []) + [here]:
        if d.is_dir():
            return d
    return None

