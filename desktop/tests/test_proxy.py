"""HTTP route tests for the desktop server."""

from __future__ import annotations

import json
import threading
import urllib.request

import pytest

import server
from server import make_server, pick_ephemeral_port


def _post(url: str, body: bytes) -> bytes:
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read()


@pytest.fixture()
def desktop_http():
    port = pick_ephemeral_port()
    httpd = make_server("127.0.0.1", port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def test_cmd_hover_emits_cmd_then_pilot(desktop_http: str) -> None:
    server.SESSION.note_side(640)
    server.HUB.note_complete_for_test(640, 640, now=0.0)
    server.SESSION.lines.clear()
    _post(f"{desktop_http}/cmd", json.dumps({"cmd": "HOVER"}).encode("utf-8"))
    assert server.SESSION.lines == ["CMD HOVER", "PILOT HOVER 0 0 0 640 640"]


def test_connect_empty_host_not_connected(desktop_http: str) -> None:
    body = _post(f"{desktop_http}/connect", json.dumps({"host": ""}).encode("utf-8"))
    assert json.loads(body.decode("utf-8")) == {"ok": True, "connected": False}
