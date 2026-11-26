"""End-to-end: needs whisper-cli (vendor/bin or PATH) and a small model."""
import os

import pytest

from autosub.core import binaries, models
from autosub.core.errors import AutoSubError
from autosub.core.pipeline import JobOptions, Pipeline, Reporter
from autosub.core.process import CancelToken


def _model():
    for name in ("tiny", "base"):
        if models.is_installed(name):
            return name
    return None


def _ready():
    try:
        binaries.find("whisper-cli")
    except AutoSubError:
        return False
    return _model() is not None


pytestmark = pytest.mark.skipif(not _ready(), reason="whisper-cli or tiny/base model not available "
                                "(set AUTOSUB_MODELS_DIR)")


class Rec(Reporter):
    def __init__(self):
        self.stages, self.segments, self.overall = [], [], []

    def stage(self, key, label):
        self.stages.append(key)

    def progress(self, f, overall):
        self.overall.append(overall)

    def segment(self, label, seg):
        self.segments.append((label, seg.text))


def test_translate_keep_both(tmp_path, speech_video):
    m = _model()
    rec = Rec()
    res = Pipeline(JobOptions(input=speech_video, translate=True, keep_original=True, transcribe_model=m,
                              translate_model=m, output_dir=tmp_path, save_srt=True, device="cpu"), rec).run()
    assert rec.stages == ["extract", "transcribe", "translate", "embed", "done"]
    # tiny/base may mis-detect synthetic speech, so only check the structure
    assert len(res.tracks) == 2 and res.tracks[0].language == "en" and res.tracks[0].translated
    assert res.tracks[1].language != "en" and not res.tracks[1].translated
    assert res.output.exists() and len(res.srt_files) == 2
    assert rec.overall == sorted(rec.overall) and rec.overall[-1] == 1.0
    assert any(label == "English" for label, _ in rec.segments)


def test_cancel_cleans_up(tmp_path, speech_video):
    tok = CancelToken()

    class CancelOnTranscribe(Rec):
        def stage(self, key, label):
            if key == "transcribe":
                tok.cancel()

    from autosub.core.errors import Cancelled
    with pytest.raises(Cancelled):
        Pipeline(JobOptions(input=speech_video, transcribe_model=_model(), output_dir=tmp_path),
                 CancelOnTranscribe(), tok).run()
    assert not [p for p in os.listdir(tmp_path) if "subbed" in p or "partial" in p]


def test_repair_replaces_looping_stretch(tmp_path, speech_video):
    """Simulate Whisper getting stuck and check the stretch is re-transcribed."""
    from autosub.core.media import extract_audio, probe
    from autosub.core.subtitles import Segment, find_loops
    from autosub.core.transcribe import WhisperOptions
    wav = extract_audio(probe(speech_video), tmp_path / "a.wav")
    looped = [Segment(i * 0.5, i * 0.5 + 0.5, "Subtitles by the community") for i in range(10)]
    pipe = Pipeline(JobOptions(input=speech_video, transcribe_model=_model(), device="cpu"), Rec())
    pipe._current = "transcribe"
    opts = WhisperOptions(model_path=models.path_for(_model()), device="cpu")
    fixed = pipe._repair_loops(wav, opts, looped, "es", tmp_path)
    assert fixed and not find_loops(fixed)
    assert "Subtitles by the community" not in [s.text for s in fixed]
