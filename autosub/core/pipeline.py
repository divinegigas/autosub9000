"""The subtitle pipeline: probe → extract audio → transcribe → translate →
(review) → embed. Shared by the GUI and CLI; reports through a Reporter."""

from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import config
from . import models
from .errors import AutoSubError
from .languages import name_of
from .media import MediaInfo, extract_audio, probe
from .mux import EmbedTrack, bundled_fonts_dir, embed, output_path_for, save_sidecar_srts
from .process import CancelToken
from .subtitles import Segment, SubtitleTrack, write_srt
from .transcribe import WhisperOptions, run_whisper

STAGES = {
    "extract": "Extracting audio",
    "transcribe": "Transcribing",
    "translate": "Translating",
    "review": "Reviewing",
    "embed": "Embedding",
    "done": "Done",
}


@dataclass
class JobOptions:
    input: Path
    source_language: str = "auto"
    translate: bool = False
    keep_original: bool = True
    transcribe_model: str = models.DEFAULT_TRANSCRIBE
    translate_model: str = models.DEFAULT_TRANSLATE
    output_format: str = "mkv"
    output_dir: Path | None = None
    output_path: Path | None = None
    save_srt: bool = False
    burn_in: bool = False
    device: str = "auto"
    audio_track: int = 0
    srt_only: bool = False  # skip embedding (CLI --srt-only)


@dataclass
class JobResult:
    input: Path
    output: Path | None
    srt_files: list[Path]
    tracks: list[SubtitleTrack]
    device: str
    elapsed: float
    warnings: list[str] = field(default_factory=list)


class Reporter:
    """Override what you need. Called from the worker thread."""

    def stage(self, key: str, label: str) -> None: ...
    def progress(self, stage_fraction: float, overall: float) -> None: ...
    def segment(self, track_label: str, seg: Segment) -> None: ...
    def log(self, line: str) -> None: ...
    def device(self, device: str) -> None: ...
    def warning(self, message: str) -> None: ...


ReviewFn = Callable[[MediaInfo, list[SubtitleTrack]], "list[SubtitleTrack] | None"]


def translation_model_check(name: str) -> str | None:
    """Return a warning if this model is a poor choice for translation."""
    info = models.BY_NAME.get(name)
    if info and not info.can_translate:
        return (f"{name} does not translate reliably – it often just transcribes in the "
                "original language. Use large-v3 or medium for translation.")
    return None


def resolve_translate_model(requested: str) -> tuple[str, str | None]:
    """Pick the model actually used for translation and an optional warning."""
    warn = translation_model_check(requested)
    if not warn:
        return requested, None
    alt = models.best_translate_model()
    if alt:
        return alt, f"{warn} Using {alt} for translation instead."
    return requested, f"{warn} No better model is installed, so translation may fail."


class Pipeline:
    def __init__(self, opts: JobOptions, reporter: Reporter | None = None,
                 cancel: CancelToken | None = None, review: ReviewFn | None = None):
        self.o = opts
        self.r = reporter or Reporter()
        self.cancel = cancel or CancelToken()
        self.review = review
        self._weights: dict[str, float] = {}
        self._done: float = 0.0
        self._current: str = ""

    # ---------------------------------------------------------- progress helpers
    def _plan(self, two_passes: bool, single_pass_key: str):
        w = {"extract": 4.0}
        if two_passes:
            w["transcribe"] = 45.0
            w["translate"] = 45.0
        else:
            w[single_pass_key] = 88.0
        if not self.o.srt_only:
            w["embed"] = 30.0 if self.o.burn_in else 4.0
        total = sum(w.values())
        self._weights = {k: v / total for k, v in w.items()}

    def _stage(self, key: str):
        if self._current in self._weights:
            self._done += self._weights[self._current]
        self._current = key
        self.r.stage(key, STAGES[key])
        self.r.progress(0.0, self._done)

    def _prog(self, f: float):
        w = self._weights.get(self._current, 0.0)
        self.r.progress(f, min(1.0, self._done + w * f))

    # ---------------------------------------------------------- main
    def run(self) -> JobResult:
        o = self.o
        t0 = time.monotonic()
        warnings: list[str] = []
        log = self.r.log
        log(f"=== {o.input}")

        if not models.is_installed(o.transcribe_model) and not (o.translate and not o.keep_original):
            raise AutoSubError(f"The model “{o.transcribe_model}” isn't installed.",
                               "Download it in the Model Manager, or pick another model.")
        tr_model = o.translate_model
        if o.translate:
            tr_model, warn = resolve_translate_model(o.translate_model)
            if warn:
                warnings.append(warn)
                self.r.warning(warn)
            if not models.is_installed(tr_model):
                raise AutoSubError(f"The translation model “{tr_model}” isn't installed.",
                                   "Download it in the Model Manager, or pick another model.")

        info = probe(o.input, log=log)
        log(f"duration {info.duration:.1f}s, {len(info.audio_streams)} audio, "
            f"{len(info.subtitle_streams)} existing subtitle track(s)")

        two_passes = o.translate and o.keep_original
        self._plan(two_passes, "translate" if o.translate else "transcribe")

        cache = config.cache_dir()
        cache.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="job-", dir=cache))
        try:
            return self._run(info, work, tr_model, warnings, t0)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _whisper(self, wav: Path, model: str, language: str, translate: bool, label: str, work: Path):
        opts = WhisperOptions(model_path=models.path_for(model), language=language,
                              translate=translate, device=self.o.device)
        self.r.log(f"--- whisper: model={model} language={language} translate={translate}")
        res = run_whisper(wav, opts, cancel=self.cancel, progress=self._prog,
                          on_segment=lambda s: self.r.segment(label, s),
                          log=self.r.log, work_dir=work)
        self.r.device(res.device)
        self.r.log(f"--- whisper finished on {res.device}: {len(res.segments)} lines, language={res.language}")
        return res

    def _run(self, info: MediaInfo, work: Path, tr_model: str, warnings: list[str], t0: float) -> JobResult:
        o = self.o
        self._stage("extract")
        wav = extract_audio(info, work / "audio.wav", audio_track=o.audio_track,
                            cancel=self.cancel, progress=self._prog, log=self.r.log)
        self.cancel.check()

        tracks: list[SubtitleTrack] = []
        device = "CPU"
        lang = o.source_language or "auto"

        if not o.translate or o.keep_original:
            self._stage("transcribe")
            res = self._whisper(wav, o.transcribe_model, lang, False, "original", work)
            device = res.device
            lang = res.language if lang == "auto" else lang
            tracks.append(SubtitleTrack(lang, res.segments, translated=False))
            self.cancel.check()

        if o.translate:
            if lang == "en":
                msg = "The audio is already in English – no translation needed."
                self.r.log(msg)
                if not tracks:  # translate-only mode: still need English subtitles
                    self._stage("translate")
                    res = self._whisper(wav, o.transcribe_model if models.is_installed(o.transcribe_model)
                                        else tr_model, "en", False, "English", work)
                    device = res.device
                    tracks.append(SubtitleTrack("en", res.segments, translated=False))
            else:
                self._stage("translate")
                res = self._whisper(wav, tr_model, lang, True, "English", work)
                device = res.device
                if lang == "auto":
                    lang = res.language
                if not o.keep_original:
                    # Remember what it was translated from, for the track title.
                    self.r.log(f"translated from {name_of(lang)}")
                tracks.insert(0, SubtitleTrack("en", res.segments, translated=True))
            self.cancel.check()

        tracks = [t for t in tracks if t.segments]
        if not tracks:
            raise AutoSubError("No speech was found in this file.",
                               "Check that the right audio track is used, or try a larger model.")

        if self.review:
            self._stage("review")
            reviewed = self.review(info, tracks)
            if reviewed is None:
                from .errors import Cancelled
                raise Cancelled()
            tracks = [t for t in reviewed if t.segments]
            self.cancel.check()

        out_path: Path | None = None
        srt_files: list[Path] = []
        if not o.srt_only:
            self._stage("embed")
            embeds = []
            for i, t in enumerate(tracks):
                p = work / f"track{i}.{t.language}.srt"
                write_srt(t.segments, p)
                embeds.append(EmbedTrack(t, p))
            target = o.output_path or output_path_for(o.input, o.output_dir, o.output_format)
            burn = None
            if o.burn_in:
                burn = next((e for e in embeds if e.track.language == "en"), embeds[0])
            out_path = embed(info, embeds, target, fmt=o.output_format, burn=burn,
                             fonts_dir=bundled_fonts_dir(), cancel=self.cancel,
                             progress=self._prog, log=self.r.log)
            self.r.log(f"wrote {out_path}")

        if o.save_srt or o.srt_only:
            base = out_path or output_path_for(o.input, o.output_dir, "srt", suffix="")
            srt_files = save_sidecar_srts(tracks, base.with_suffix(".mkv") if out_path is None else base)
            for p in srt_files:
                self.r.log(f"wrote {p}")

        self._stage("done")
        self.r.progress(1.0, 1.0)
        return JobResult(o.input, out_path, srt_files, tracks, device,
                         time.monotonic() - t0, warnings)
