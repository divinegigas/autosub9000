"""Command-line interface – the same core as the GUI.

Examples:
  autosub9000 --input video.mkv
  autosub9000 --input video.mkv --translate --keep-original
  autosub9000 --input a.mp4 b.mkv --translate --format mp4 --srt
  autosub9000 --list-models
  autosub9000 --download-model large-v3-turbo
  autosub9000 --check-gpu
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import APP_NAME, __version__, config
from .core import models
from .core.errors import AutoSubError, Cancelled, friendly
from .core.languages import LANGUAGES
from .core.pipeline import JobOptions, Pipeline, Reporter, translation_model_check
from .core.process import CancelToken


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="autosub9000", description=f"{APP_NAME} – offline subtitles with whisper.cpp")
    p.add_argument("--input", "-i", nargs="+", type=Path, metavar="VIDEO", help="video file(s) to process, in order")
    p.add_argument("--language", "-l", default="auto", help="source language code (default: auto-detect), e.g. ja, de")
    p.add_argument("--translate", "-t", action="store_true", help="translate to English")
    p.add_argument("--keep-original", action=argparse.BooleanOptionalAction, default=True,
                   help="when translating, also keep the original-language track (default: on)")
    p.add_argument("--model", "-m", default=None, help=f"transcription model (default: {models.DEFAULT_TRANSCRIBE})")
    p.add_argument("--translate-model", default=None, help=f"translation model (default: {models.DEFAULT_TRANSLATE})")
    p.add_argument("--format", "-f", choices=["mkv", "mp4"], default="mkv", help="output container (default: mkv)")
    p.add_argument("--output", "-o", type=Path, help="output file (single input only)")
    p.add_argument("--output-dir", type=Path, help="output folder (default: next to the input)")
    p.add_argument("--srt", action="store_true", help="also save separate .srt files")
    p.add_argument("--srt-only", action="store_true", help="only write .srt files, don't create a new video")
    p.add_argument("--burn", action="store_true", help="also burn subtitles into the picture (re-encodes video)")
    p.add_argument("--device", choices=["auto", "gpu", "cpu"], default="auto", help="compute device (default: auto)")
    p.add_argument("--audio-track", type=int, default=0, help="audio track index to transcribe (default: 0)")
    p.add_argument("--quiet", "-q", action="store_true", help="only print errors and results")
    p.add_argument("--verbose", "-v", action="store_true", help="print the full ffmpeg/whisper log")
    p.add_argument("--list-models", action="store_true", help="list Whisper models and exit")
    p.add_argument("--download-model", nargs="+", metavar="NAME", help="download model(s) and exit")
    p.add_argument("--list-languages", action="store_true", help="list language codes and exit")
    p.add_argument("--check-gpu", action="store_true", help="report Vulkan/GPU detection and exit")
    p.add_argument("--gui", action="store_true", help="start the graphical interface")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return p


class ConsoleReporter(Reporter):
    def __init__(self, quiet: bool, verbose: bool):
        self.quiet, self.verbose = quiet, verbose
        self.label = ""
        self._last = 0.0
        self.tty = sys.stderr.isatty()

    def _bar(self, stage_f: float, overall: float):
        if self.quiet:
            return
        now = time.monotonic()
        if now - self._last < 0.2 and overall < 1.0:
            return
        self._last = now
        if self.tty:
            n = int(overall * 30)
            sys.stderr.write(f"\r\033[K  [{'█' * n}{'░' * (30 - n)}] {overall * 100:5.1f}%  {self.label}")
            sys.stderr.flush()

    def stage(self, key, label):
        self.label = label
        if not self.quiet:
            sys.stderr.write(("\r\033[K" if self.tty else "") + f"» {label}\n")

    def progress(self, stage_fraction, overall):
        self._bar(stage_fraction, overall)

    def segment(self, track_label, seg):
        if not self.quiet and not self.verbose:
            from .core.subtitles import format_ts
            sys.stderr.write(("\r\033[K" if self.tty else "") +
                             f"    {format_ts(seg.start, '.')[3:]}  {seg.text}\n")

    def log(self, line):
        if self.verbose:
            sys.stderr.write(("\r\033[K" if self.tty else "") + f"    | {line}\n")

    def device(self, device):
        if not self.quiet:
            sys.stderr.write(("\r\033[K" if self.tty else "") + f"  running on {device}\n")

    def warning(self, message):
        sys.stderr.write(("\r\033[K" if self.tty else "") + f"  ! {message}\n")


def cmd_list_models():
    print(f"Models folder: {config.models_dir()}\n")
    print(f"  {'name':<16}{'size':>9}  {'speed':<10}{'accuracy':<11}{'installed':<10} notes")
    for m in models.CATALOGUE:
        inst = "yes" if models.is_installed(m.name) else "-"
        print(f"  {m.name:<16}{m.size_mb:>6} MB  {m.speed:<10}{m.accuracy:<11}{inst:<10} {m.notes}")


def cmd_download(names: list[str]) -> int:
    for name in names:
        info = models.get(name)
        if models.is_installed(name):
            print(f"{name}: already installed")
            continue
        print(f"{name}: downloading {info.size_mb} MB from {info.url}")
        last = [0.0]

        def prog(done, total, phase):
            now = time.monotonic()
            if now - last[0] > 0.3 or done >= total:
                last[0] = now
                sys.stderr.write(f"\r\033[K  {phase:<8} {done / max(1, total) * 100:5.1f}%  "
                                 f"{done / 1e6:,.0f}/{total / 1e6:,.0f} MB")
        models.download(name, prog)
        sys.stderr.write("\n")
        print(f"{name}: installed and verified")
    return 0


def cmd_check_gpu() -> int:
    from .core.transcribe import probe_devices
    info = probe_devices()
    print(f"whisper-cli:       {info.get('whisper_cli') or 'NOT FOUND'}")
    if info.get("error"):
        print(f"error:             {info['error']}")
        return 1
    print(f"Vulkan module:     {'present' if info.get('vulkan_module') else 'missing (CPU-only build)'}")
    print(f"System libvulkan:  {info.get('libvulkan') or 'NOT FOUND – install vulkan-loader'}")
    if info["devices"]:
        for d in info["devices"]:
            print(f"Vulkan device:     {d}")
        print("Result:            GPU acceleration available ✔")
    else:
        print("Vulkan device:     none detected")
        print("Result:            will run on CPU (see README → Troubleshooting → GPU)")
    return 0


def run_jobs(args) -> int:
    settings = config.Settings.load()
    tmodel = args.model or settings.transcribe_model or models.DEFAULT_TRANSCRIBE
    trmodel = args.translate_model or settings.translate_model or models.DEFAULT_TRANSLATE
    if args.language != "auto" and args.language not in LANGUAGES:
        print(f"error: unknown language code '{args.language}' (see --list-languages)", file=sys.stderr)
        return 2
    if args.output and len(args.input) > 1:
        print("error: --output only works with a single input; use --output-dir", file=sys.stderr)
        return 2
    if args.translate:
        warn = translation_model_check(trmodel)
        if warn and not args.quiet:
            print(f"warning: {warn}", file=sys.stderr)

    cancel = CancelToken()
    failures = 0
    for n, path in enumerate(args.input, 1):
        if len(args.input) > 1 and not args.quiet:
            print(f"\n[{n}/{len(args.input)}] {path.name}", file=sys.stderr)
        opts = JobOptions(input=path, source_language=args.language, translate=args.translate,
                          keep_original=args.keep_original, transcribe_model=tmodel,
                          translate_model=trmodel, output_format=args.format,
                          output_dir=args.output_dir, output_path=args.output,
                          save_srt=args.srt, burn_in=args.burn, device=args.device,
                          audio_track=args.audio_track, srt_only=args.srt_only)
        rep = ConsoleReporter(args.quiet, args.verbose)
        try:
            res = Pipeline(opts, rep, cancel).run()
        except KeyboardInterrupt:
            cancel.cancel()
            print("\ncancelled", file=sys.stderr)
            return 130
        except Cancelled:
            print("\ncancelled", file=sys.stderr)
            return 130
        except Exception as e:  # noqa: BLE001
            err = friendly(e)
            print(f"\nerror: {err.message}", file=sys.stderr)
            if err.hint:
                print(f"       {err.hint}", file=sys.stderr)
            if err.details and args.verbose:
                print(err.details, file=sys.stderr)
            failures += 1
            continue
        sys.stderr.write("\r\033[K" if sys.stderr.isatty() else "")
        tracks = ", ".join(t.title for t in res.tracks)
        print(f"✔ {path.name}: {tracks} – {res.elapsed:.1f}s on {res.device}", file=sys.stderr)
        if res.output:
            print(res.output)
        for p in res.srt_files:
            print(p)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.list_models:
            cmd_list_models()
            return 0
        if args.list_languages:
            for code, (name, iso) in sorted(LANGUAGES.items(), key=lambda x: x[1][0]):
                print(f"  {code:<5}{iso:<5}{name}")
            return 0
        if args.download_model:
            return cmd_download(args.download_model)
        if args.check_gpu:
            return cmd_check_gpu()
        if not args.input:
            build_parser().print_help()
            return 2
        return run_jobs(args)
    except KeyboardInterrupt:
        return 130
    except AutoSubError as e:
        print(f"error: {e.message}", file=sys.stderr)
        if e.hint:
            print(f"       {e.hint}", file=sys.stderr)
        return 1

