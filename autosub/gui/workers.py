"""Background workers. All heavy work runs in QThreads; the GUI only receives
signals (which Qt delivers on the main thread)."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from ..core import models
from ..core.errors import Cancelled, friendly
from ..core.pipeline import JobOptions, Pipeline, Reporter
from ..core.process import CancelToken


class _QtReporter(Reporter):
    def __init__(self, w: "JobWorker"):
        self.w = w

    def stage(self, key, label):
        self.w.stage.emit(key, label)

    def progress(self, stage_fraction, overall):
        self.w.progress.emit(stage_fraction, overall)

    def segment(self, track_label, seg):
        self.w.segment.emit(track_label, seg.start, seg.end, seg.text)

    def log(self, line):
        self.w.log.emit(line)

    def device(self, device):
        self.w.device.emit(device)

    def warning(self, message):
        self.w.warning.emit(message)


class JobWorker(QThread):
    """Processes a queue of files one after another."""

    jobStarted = Signal(int, str)            # index, file name
    stage = Signal(str, str)                 # key, label
    progress = Signal(float, float)          # stage fraction, overall fraction
    segment = Signal(str, float, float, str)
    log = Signal(str)
    device = Signal(str)
    warning = Signal(str)
    jobFinished = Signal(int, object)        # index, JobResult
    jobFailed = Signal(int, str, str, str)   # index, message, hint, details
    reviewRequested = Signal(object, object)  # MediaInfo, list[SubtitleTrack]
    allDone = Signal(bool)                   # cancelled?

    def __init__(self, files: list[Path], base: JobOptions, review: bool, parent=None):
        super().__init__(parent)
        self.files = list(files)
        self.base = base
        self.review_enabled = review
        self.cancel_token = CancelToken()
        self._review_event = threading.Event()
        self._review_result = None

    def cancel(self):
        self.cancel_token.cancel()
        self._review_result = None
        self._review_event.set()

    # called from the GUI thread when the editor closes
    def submitReview(self, tracks):
        self._review_result = tracks
        self._review_event.set()

    def _review(self, info, tracks):
        self._review_event.clear()
        self._review_result = None
        self.reviewRequested.emit(info, tracks)
        while not self._review_event.wait(0.2):
            if self.cancel_token.cancelled:
                return None
        return self._review_result

    def run(self):
        cancelled = False
        for i, f in enumerate(self.files):
            if self.cancel_token.cancelled:
                cancelled = True
                break
            self.jobStarted.emit(i, f.name)
            opts = replace(self.base, input=f)
            pipe = Pipeline(opts, _QtReporter(self), self.cancel_token,
                            review=self._review if self.review_enabled else None)
            try:
                res = pipe.run()
            except Cancelled:
                cancelled = True
                self.log.emit("--- cancelled")
                break
            except Exception as e:  # noqa: BLE001 – converted to a friendly message
                err = friendly(e)
                if err.details:
                    self.log.emit(err.details)
                self.jobFailed.emit(i, err.message, err.hint, err.details)
                continue
            self.jobFinished.emit(i, res)
        self.allDone.emit(cancelled or self.cancel_token.cancelled)


class DownloadWorker(QThread):
    progress = Signal(str, int, int, str)   # name, done, total, phase
    finished_one = Signal(str, bool, str, str)  # name, ok, message, hint
    allDone = Signal()

    def __init__(self, names: list[str], parent=None):
        super().__init__(parent)
        self.names = names
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        for name in self.names:
            if self._cancel.is_set():
                break
            try:
                models.download(name, lambda d, t, ph, n=name: self.progress.emit(n, d, t, ph),
                                cancel=self._cancel.is_set)
                self.finished_one.emit(name, True, "", "")
            except Cancelled:
                self.finished_one.emit(name, False, "Cancelled", "The partial download is kept and will resume.")
                break
            except Exception as e:  # noqa: BLE001
                err = friendly(e)
                self.finished_one.emit(name, False, err.message, err.hint)
        self.allDone.emit()


class ImportWorker(QThread):
    done = Signal(str, bool, str)
    progress = Signal(float)

    def __init__(self, name: str, path: Path, parent=None):
        super().__init__(parent)
        self.name, self.path = name, path

    def run(self):
        try:
            models.import_file(self.name, self.path, self.progress.emit)
            self.done.emit(self.name, True, "")
        except Exception as e:  # noqa: BLE001
            self.done.emit(self.name, False, str(friendly(e)))


class OnlineCheck(QThread):
    result = Signal(bool)

    def run(self):
        self.result.emit(models.is_online())


class _Keep(QObject):
    """Keeps short-lived threads alive until they finish."""
    threads: set = set()

    @classmethod
    def start(cls, t: QThread):
        cls.threads.add(t)
        t.finished.connect(lambda: cls.threads.discard(t))
        t.start()
        return t


start_detached = _Keep.start
