"""Cancellable subprocess runner with line-by-line callbacks for stdout/stderr."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from typing import Callable

from .errors import Cancelled


class CancelToken:
    """Shared cancel flag. Running processes register themselves so cancel()
    can kill them immediately."""

    def __init__(self):
        self._event = threading.Event()
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise Cancelled()

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            procs = list(self._procs)
        for p in procs:
            _kill_tree(p)

    def _register(self, p):
        with self._lock:
            self._procs.add(p)
        if self._event.is_set():
            _kill_tree(p)

    def _unregister(self, p):
        with self._lock:
            self._procs.discard(p)


def _kill_tree(p: subprocess.Popen) -> None:
    if p.poll() is not None:
        return
    try:
        os.killpg(p.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        p.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


LineCb = Callable[[str], None]


def run(cmd: list[str], *, cancel: CancelToken | None = None,
        on_stdout: LineCb | None = None, on_stderr: LineCb | None = None,
        log: LineCb | None = None, cwd: str | None = None,
        env: dict | None = None) -> tuple[int, list[str], list[str]]:
    """Run cmd, streaming lines to callbacks. Returns (returncode, stdout, stderr).
    Raises Cancelled if the token was cancelled."""
    if cancel:
        cancel.check()
    if log:
        log("$ " + " ".join(_q(c) for c in cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         stdin=subprocess.DEVNULL, cwd=cwd, env=env,
                         start_new_session=True)
    if cancel:
        cancel._register(p)
    out_lines: list[str] = []
    err_lines: list[str] = []

    def pump(stream, sink: list[str], cb: LineCb | None):
        # whisper.cpp and ffmpeg use \r for progress updates; split on both.
        buf = b""
        while True:
            chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(4096)
            if not chunk:
                break
            buf += chunk
            while True:
                idx = min((i for i in (buf.find(b"\n"), buf.find(b"\r")) if i >= 0), default=-1)
                if idx < 0:
                    break
                line, buf = buf[:idx], buf[idx + 1:]
                _emit(line, sink, cb)
        if buf:
            _emit(buf, sink, cb)

    def _emit(raw: bytes, sink, cb):
        line = raw.decode("utf-8", errors="replace").rstrip()
        if not line:
            return
        sink.append(line)
        if len(sink) > 5000:
            del sink[:1000]
        if cb:
            try:
                cb(line)
            except Exception:  # never let a UI callback kill the pump
                pass

    t1 = threading.Thread(target=pump, args=(p.stdout, out_lines, on_stdout), daemon=True)
    t2 = threading.Thread(target=pump, args=(p.stderr, err_lines, on_stderr), daemon=True)
    t1.start(); t2.start()
    try:
        p.wait()
    finally:
        t1.join(); t2.join()
        if cancel:
            cancel._unregister(p)
    if cancel and cancel.cancelled:
        raise Cancelled()
    return p.returncode, out_lines, err_lines


def _q(s: str) -> str:
    return s if s and all(c.isalnum() or c in "-_./=:,+%" for c in s) else repr(s)
