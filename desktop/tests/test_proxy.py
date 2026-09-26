"""HTTP route tests for the desktop server."""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
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


def test_connect_closed_port_not_connected(desktop_http: str) -> None:
    body = _post(
        f"{desktop_http}/connect",
        json.dumps({"host": "127.0.0.1"}).encode("utf-8"),
    )
    assert json.loads(body.decode("utf-8")) == {"ok": True, "connected": False}
    assert server._esp_connected is False


def test_connect_overlapping_posts_consistent_state(
    desktop_http: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    port = pick_ephemeral_port()
    monkeypatch.setattr(server, "ESP_TCP_PORT", port)

    listen_ready = threading.Event()
    release = threading.Event()
    conns: list[socket.socket] = []

    def accept_loop() -> None:
        lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        lsock.bind(("127.0.0.1", port))
        lsock.listen(4)
        listen_ready.set()
        lsock.settimeout(0.5)
        while len(conns) < 4 and not release.is_set():
            try:
                conn, _ = lsock.accept()
                conns.append(conn)
            except TimeoutError:
                pass
        release.wait(timeout=15)
        for conn in conns:
            conn.close()
        lsock.close()

    threading.Thread(target=accept_loop, daemon=True, name="esp-fake").start()
    assert listen_ready.wait(timeout=2)

    results: list[dict[str, object]] = []
    errors: list[BaseException] = []

    def post_connect() -> None:
        try:
            body = _post(
                f"{desktop_http}/connect",
                json.dumps({"host": "127.0.0.1"}).encode("utf-8"),
            )
            results.append(json.loads(body.decode("utf-8")))
        except BaseException as exc:
            errors.append(exc)

    t1 = threading.Thread(target=post_connect)
    t2 = threading.Thread(target=post_connect)
    t1.start()
    t2.start()
    t1.join(timeout=20)
    t2.join(timeout=20)
    release.set()

    assert not errors
    assert len(results) == 2
    any_connected = any(bool(r.get("connected")) for r in results)
    if any_connected:
        assert server._esp_connected is True
    else:
        assert server._esp_connected is False

    if server._tcp_thread is not None and server._tcp_thread.is_alive():
        server._tcp_stop.set()
        server._tcp_thread.join(timeout=2)


def test_cmd_chase_returns_400(desktop_http: str) -> None:
    url = f"{desktop_http}/cmd"
    req = urllib.request.Request(
        url,
        data=json.dumps({"cmd": "CHASE"}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5)
    assert exc_info.value.code == 400
