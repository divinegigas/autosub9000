import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


@pytest.fixture
def sample_video(tmp_path):
    """3 s test video with a tone, no speech (enough for muxing tests)."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    out = tmp_path / "clip.mkv"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "3", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)], check=True)
    return out


@pytest.fixture
def speech_video(tmp_path):
    """Short Spanish speech clip made with espeak-ng (for pipeline tests)."""
    if not (shutil.which("ffmpeg") and shutil.which("espeak-ng")):
        pytest.skip("ffmpeg/espeak-ng not installed")
    wav = tmp_path / "es.wav"
    subprocess.run(["espeak-ng", "-v", "es", "-s", "140", "-w", str(wav),
                    "Hola, buenos días. Me llamo Carlos y vivo en Madrid."], check=True)
    out = tmp_path / "speech.mkv"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
                    "-i", str(wav), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    str(out)], check=True)
    return out
