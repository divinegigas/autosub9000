import hashlib
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from autosub.core import updater
from autosub.core.errors import AutoSubError


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    httpd.RequestHandlerClass.log_message = lambda *a: None
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield tmp_path, f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def publish(root, base, version, payload=b"#!/bin/sh\necho new\n", sha=None):
    name = f"AutoSub9000-{version}-x86_64.AppImage"
    (root / name).write_bytes(payload)
    (root / f"{name}.sha256").write_text(f"{sha or hashlib.sha256(payload).hexdigest()}  {name}\n")
    (root / "latest.json").write_text(json.dumps({
        "tag_name": f"v{version}", "body": "notes", "html_url": base,
        "assets": [{"name": name, "size": len(payload), "browser_download_url": f"{base}/{name}"},
                   {"name": f"{name}.sha256", "browser_download_url": f"{base}/{name}.sha256"}]}))


def test_versions():
    assert updater.parse_version("1.10.0") > updater.parse_version("1.9.9")
    assert updater.parse_version("v2.0") > updater.parse_version("1.99.99")


def test_check_and_install(server, monkeypatch, tmp_path_factory):
    root, base = server
    publish(root, base, "99.0.0")
    monkeypatch.setattr(updater, "API_URL", f"{base}/latest.json")
    rel = updater.check()
    assert rel.version == "99.0.0" and rel.is_newer and rel.notes == "notes"
    target = tmp_path_factory.mktemp("apps") / "AutoSub9000.AppImage"
    target.write_text("old")
    updater.install(rel, target=target)
    assert target.read_bytes().startswith(b"#!/bin/sh") and target.stat().st_mode & 0o111


def test_bad_checksum_changes_nothing(server, monkeypatch, tmp_path_factory):
    root, base = server
    publish(root, base, "99.0.0", sha="0" * 64)
    monkeypatch.setattr(updater, "API_URL", f"{base}/latest.json")
    target = tmp_path_factory.mktemp("apps") / "AutoSub9000.AppImage"
    target.write_text("old")
    with pytest.raises(AutoSubError, match="checksum"):
        updater.install(updater.check(), target=target)
    assert target.read_text() == "old"
    assert list(target.parent.iterdir()) == [target]


def test_no_releases(server, monkeypatch):
    _, base = server
    monkeypatch.setattr(updater, "API_URL", f"{base}/missing.json")
    assert updater.check() is None
