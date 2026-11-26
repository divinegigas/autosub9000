"""Subtitle data model and SRT reading/writing, merge/split helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Segment:
    start: float  # seconds
    end: float  # seconds
    text: str

    def copy(self) -> "Segment":
        return Segment(self.start, self.end, self.text)


@dataclass
class SubtitleTrack:
    """One subtitle track (e.g. Japanese original or English translation)."""

    language: str  # whisper code, e.g. "ja"
    segments: list[Segment] = field(default_factory=list)
    translated: bool = False

    @property
    def title(self) -> str:
        from .languages import name_of

        return f"{name_of(self.language)} ({'translated' if self.translated else 'original'})"


# ---------------------------------------------------------------- timestamps

def format_ts(seconds: float, sep: str = ",") -> str:
    if seconds < 0:
        seconds = 0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


_TS_RE = re.compile(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?\s*$")


def parse_ts(text: str) -> float:
    """Parse 'HH:MM:SS,mmm', 'MM:SS.mmm', or plain seconds. Raises ValueError."""
    text = text.strip()
    m = _TS_RE.match(text)
    if m:
        h, mi, s, ms = m.groups()
        return int(h or 0) * 3600 + int(mi) * 60 + int(s) + (int(ms.ljust(3, "0")) / 1000 if ms else 0)
    return float(text)


# ---------------------------------------------------------------- SRT

def to_srt(segments: list[Segment]) -> str:
    out = []
    n = 0
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        n += 1
        end = max(seg.end, seg.start + 0.05)
        out.append(f"{n}\n{format_ts(seg.start)} --> {format_ts(end)}\n{text}\n")
    return "\n".join(out)


def write_srt(segments: list[Segment], path: Path) -> Path:
    path = Path(path)
    path.write_text(to_srt(segments), encoding="utf-8")
    return path


_SRT_TIME = re.compile(r"(\d+:\d{1,2}:\d{1,2}[,.]\d{1,3})\s*-->\s*(\d+:\d{1,2}:\d{1,2}[,.]\d{1,3})")


def parse_srt(text: str) -> list[Segment]:
    segments: list[Segment] = []
    blocks = re.split(r"\r?\n\s*\r?\n", text.strip().lstrip("﻿"))
    for block in blocks:
        lines = [l for l in block.splitlines()]
        for i, line in enumerate(lines):
            m = _SRT_TIME.search(line)
            if m:
                body = "\n".join(lines[i + 1:]).strip()
                segments.append(Segment(parse_ts(m.group(1)), parse_ts(m.group(2)), body))
                break
    return segments


def read_srt(path: Path) -> list[Segment]:
    return parse_srt(Path(path).read_text(encoding="utf-8", errors="replace"))


# ---------------------------------------------------------------- editing

def merge(segments: list[Segment], first: int, last: int) -> list[Segment]:
    """Merge segments[first..last] (inclusive) into one."""
    if first >= last:
        return segments
    group = segments[first:last + 1]
    merged = Segment(group[0].start, max(s.end for s in group),
                     " ".join(s.text.strip() for s in group if s.text.strip()))
    return segments[:first] + [merged] + segments[last + 1:]


def split(segments: list[Segment], index: int, char_pos: int | None = None) -> list[Segment]:
    """Split one segment in two. Text is split at char_pos (or the word gap nearest
    the middle); time is split proportionally to the text length."""
    seg = segments[index]
    text = seg.text.strip()
    if char_pos is None or not (0 < char_pos < len(text)):
        mid = len(text) // 2
        spaces = [i for i, c in enumerate(text) if c == " "]
        char_pos = min(spaces, key=lambda i: abs(i - mid)) if spaces else mid
    left, right = text[:char_pos].strip(), text[char_pos:].strip()
    if not left or not right:
        left, right = text, ""
    ratio = len(left) / max(1, len(left) + len(right))
    cut = seg.start + (seg.end - seg.start) * ratio
    a = Segment(seg.start, cut, left)
    b = Segment(cut, seg.end, right)
    return segments[:index] + [a, b] + segments[index + 1:]


def clean(segments: list[Segment]) -> list[Segment]:
    """Drop empty lines and whisper's non-speech markers, fix overlaps, sort."""
    out = []
    for s in sorted(segments, key=lambda s: s.start):
        t = s.text.strip()
        if not t or re.fullmatch(r"[\[\(](?:BLANK_AUDIO|blank_audio|Music|MUSIC|music|silence)[\]\)]", t):
            continue
        out.append(Segment(s.start, max(s.end, s.start + 0.2), t))
    for a, b in zip(out, out[1:]):
        if a.end > b.start:
            a.end = max(a.start + 0.05, b.start)
    return out
