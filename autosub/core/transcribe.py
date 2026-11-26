"""Run whisper.cpp (whisper-cli) and parse its output.

whisper-cli is run as a subprocess so a crash or a GPU driver problem can never
take down the GUI, and so Cancel can kill it instantly.

GPU handling:
  * whisper-cli is built with Vulkan as a loadable backend. If the system has
    a working Vulkan driver it is used automatically; otherwise whisper.cpp
    logs "no GPU found" and runs on the CPU.
  * If a GPU run *fails* (driver crash, out of VRAM...), we retry once on CPU.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import binaries
from .errors import AutoSubError, Cancelled
from .process import CancelToken, run
from .subtitles import Segment, clean

_SEG_RE = re.compile(r"^\[(\d+):(\d+):(\d+)\.(\d+)\s*-->\s*(\d+):(\d+):(\d+)\.(\d+)\]\s*(.*)$")
_PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)%")
_LANG_RE = re.compile(r"auto-detected language:\s*([a-z]+)")
_BACKEND_RE = re.compile(r"using (\S+) backend")
_VKDEV_RE = re.compile(r"ggml_vulkan:\s*\d+\s*=\s*(.+?)(?:\s*\|.*)?$")


@dataclass
class WhisperResult:
    segments: list[Segment]
    language: str
    device: str  # "GPU (<name>)" or "CPU"
    used_gpu: bool


@dataclass
class WhisperOptions:
    model_path: Path
    language: str = "auto"
    translate: bool = False
    device: str = "auto"  # auto | gpu | cpu
    threads: int = 0  # 0 = auto
    beam_size: int = 5
    # Text context carried from one 30 s window to the next. Whisper's default
    # (-1 = up to 224 tokens) lets one hallucinated line get copied forward
    # forever ("every line is the same for the rest of the film"). 0 decodes
    # each window independently, which prevents those loops.
    max_context: int = 0
    entropy_thold: float | None = None  # higher = stricter repetition check
    offset_ms: int = 0       # transcribe only part of the audio...
    duration_ms: int = 0     # ...(0 = to the end)
    extra_args: list[str] = field(default_factory=list)


def _ts(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def default_threads() -> int:
    n = os.cpu_count() or 4
    return max(1, min(8, n - 1 if n > 2 else n))


def run_whisper(wav: Path, opts: WhisperOptions, *,
                cancel: CancelToken | None = None,
                progress: Callable[[float], None] | None = None,
                on_segment: Callable[[Segment], None] | None = None,
                log: Callable[[str], None] | None = None,
                work_dir: Path | None = None) -> WhisperResult:
    if not Path(opts.model_path).is_file():
        raise AutoSubError("The selected Whisper model isn't installed.",
                           "Open the Model Manager to download it.")
    use_gpu = opts.device != "cpu"
    try:
        return _run_once(wav, opts, use_gpu, cancel, progress, on_segment, log, work_dir)
    except Cancelled:
        raise
    except AutoSubError as e:
        if not use_gpu or opts.device == "gpu":
            raise
        if log:
            log(f"!! GPU run failed ({e.message}) – retrying on CPU")
        if progress:
            progress(0.0)
        return _run_once(wav, opts, False, cancel, progress, on_segment, log, work_dir)


def _run_once(wav, opts, use_gpu, cancel, progress, on_segment, log, work_dir) -> WhisperResult:
    tmp = Path(tempfile.mkdtemp(prefix="whisper-", dir=work_dir))
    prefix = tmp / "out"
    cmd = [binaries.find("whisper-cli"),
           "-m", str(opts.model_path),
           "-f", str(wav),
           "-l", opts.language or "auto",
           "-t", str(opts.threads or default_threads()),
           "-bs", str(opts.beam_size),
           "-oj", "-of", str(prefix), "-pp"]
    cmd += ["-mc", str(opts.max_context)]
    if opts.entropy_thold is not None:
        cmd += ["-et", f"{opts.entropy_thold:.2f}"]
    if opts.offset_ms:
        cmd += ["-ot", str(int(opts.offset_ms))]
    if opts.duration_ms:
        cmd += ["-d", str(int(opts.duration_ms))]
    if opts.translate:
        cmd.append("-tr")
    if not use_gpu:
        cmd.append("-ng")
    cmd += opts.extra_args

    state = {"lang": None, "backend": None, "vkdev": None, "no_gpu": False}
    live: list[Segment] = []

    def on_out(line: str):
        m = _SEG_RE.match(line.strip())
        if m:
            g = m.groups()
            seg = Segment(_ts(*g[0:4]), _ts(*g[4:8]), g[8].strip())
            live.append(seg)
            if on_segment and seg.text:
                on_segment(seg)

    def on_err(line: str):
        if log:
            log(line)
        m = _PROGRESS_RE.search(line)
        if m and progress:
            progress(min(1.0, int(m.group(1)) / 100))
            return
        m = _LANG_RE.search(line)
        if m:
            state["lang"] = m.group(1)
        m = _BACKEND_RE.search(line)
        if m:
            state["backend"] = m.group(1)
        m = _VKDEV_RE.search(line)
        if m and not state["vkdev"]:
            state["vkdev"] = re.sub(r"\s*\([a-z_ ]+\)$", "", m.group(1).strip())
        if "no GPU found" in line:
            state["no_gpu"] = True

    env = dict(os.environ)
    code, _, err = run(cmd, cancel=cancel, on_stdout=on_out, on_stderr=on_err, log=log, env=env)

    json_path = prefix.with_suffix(".json")
    if code != 0 or not json_path.exists():
        tail = "\n".join(err[-25:])
        if "failed to load model" in tail or "invalid model" in tail:
            raise AutoSubError("The Whisper model file is damaged.",
                               "Delete it in the Model Manager and download it again.", tail)
        if any(k in tail for k in ("ErrorOutOfDeviceMemory", "out of memory", "failed to allocate")):
            raise AutoSubError("Ran out of memory while transcribing.",
                               "Try a smaller model, or switch Device to CPU.", tail)
        raise AutoSubError("Transcription failed.", "Open the log panel for details.", tail)

    try:
        data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
    except ValueError as e:
        raise AutoSubError("Couldn't read whisper.cpp's output.", "", str(e))
    segments = [Segment(item["offsets"]["from"] / 1000, item["offsets"]["to"] / 1000,
                        item.get("text", "").strip())
                for item in data.get("transcription", [])]
    lang = (data.get("result") or {}).get("language") or state["lang"] or opts.language
    if lang == "auto":
        lang = "und"

    gpu_used = use_gpu and not state["no_gpu"] and bool(state["backend"]) and state["backend"].upper() != "CPU"
    device = f"GPU ({state['vkdev'] or state['backend']})" if gpu_used else "CPU"
    if progress:
        progress(1.0)
    for f in tmp.iterdir():
        f.unlink(missing_ok=True)
    tmp.rmdir()
    return WhisperResult(clean(segments), lang, device, gpu_used)


def probe_devices(log: Callable[[str], None] | None = None) -> dict:
    """Report which compute devices whisper.cpp can see, without needing a model.

    Runs `whisper-cli --help`: the Vulkan backend module is loaded (and its devices
    enumerated) at program start."""
    info = {"whisper_cli": None, "vulkan_loaded": False, "devices": [], "error": None}
    try:
        exe = binaries.find("whisper-cli")
    except AutoSubError as e:
        info["error"] = e.message
        return info
    info["whisper_cli"] = exe
    env = dict(os.environ, GGML_VK_VISIBLE_DEVICES=os.environ.get("GGML_VK_VISIBLE_DEVICES", ""))
    if not env["GGML_VK_VISIBLE_DEVICES"]:
        env.pop("GGML_VK_VISIBLE_DEVICES")
    _, out, err = run([exe, "--help"], log=log, env=env)
    for line in out + err:
        if "ggml_vulkan" in line:
            info["vulkan_loaded"] = True
        m = _VKDEV_RE.search(line)
        if m:
            info["devices"].append(m.group(1).strip())
    # Look for the backend module and libvulkan, for the diagnostics report.
    exe_dir = Path(os.path.realpath(exe)).parent
    info["vulkan_module"] = (exe_dir / "libggml-vulkan.so").exists()
    info["libvulkan"] = _find_libvulkan()
    return info


def _find_libvulkan() -> str | None:
    import ctypes.util
    name = ctypes.util.find_library("vulkan")
    if name:
        return name
    for d in ("/usr/lib64", "/usr/lib/x86_64-linux-gnu", "/usr/lib"):
        p = Path(d) / "libvulkan.so.1"
        if p.exists():
            return str(p)
    return None
