import json
import subprocess

import pytest

from autosub.core.media import probe
from autosub.core.mux import EmbedTrack, embed, output_path_for
from autosub.core.subtitles import Segment, SubtitleTrack, write_srt


def streams(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)["streams"]


def make_tracks(tmp_path):
    en = SubtitleTrack("en", [Segment(0.2, 1.4, "Hello there"), Segment(1.6, 2.8, "General")], translated=True)
    ja = SubtitleTrack("ja", [Segment(0.2, 1.4, "こんにちは"), Segment(1.6, 2.8, "将軍")])
    return [EmbedTrack(en, write_srt(en.segments, tmp_path / "en.srt")),
            EmbedTrack(ja, write_srt(ja.segments, tmp_path / "ja.srt"))]


@pytest.mark.parametrize("fmt,codec", [("mkv", "subrip"), ("mp4", "mov_text")])
def test_embed_tracks(tmp_path, sample_video, fmt, codec):
    info = probe(sample_video)
    out = embed(info, make_tracks(tmp_path), tmp_path / f"out.{fmt}", fmt=fmt)
    st = streams(out)
    subs = [s for s in st if s["codec_type"] == "subtitle"]
    assert [s["codec_name"] for s in subs] == [codec, codec]
    assert [s["tags"]["language"] for s in subs] == ["eng", "jpn"]
    assert subs[0]["disposition"]["default"] == 1 and subs[1]["disposition"]["default"] == 0
    names = [s["tags"].get("title") or s["tags"].get("handler_name") for s in subs]
    assert names == ["English (translated)", "Japanese (original)"]
    # video/audio are stream-copied, not re-encoded
    src = {s["codec_type"]: s for s in streams(sample_video)}
    for s in st:
        if s["codec_type"] in ("video", "audio"):
            assert s["codec_name"] == src[s["codec_type"]]["codec_name"]
    assert sample_video.exists()  # original untouched


def test_never_overwrites_original(tmp_path, sample_video):
    out = output_path_for(sample_video, None, "mkv")
    assert out != sample_video and out.name == "clip.subbed.mkv"
    out.write_bytes(b"x")
    assert output_path_for(sample_video, None, "mkv").name == "clip.subbed (2).mkv"
    from autosub.core.errors import AutoSubError
    with pytest.raises(AutoSubError):
        embed(probe(sample_video), make_tracks(tmp_path), sample_video)
