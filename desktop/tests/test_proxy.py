"""Proxy route tests against a fake Pi HTTP server."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from server import make_server, pick_ephemeral_port, set_pi_host, set_pi_http_port


class FakePiState:
    last_preset_body: bytes | None = None
    last_cmd_body: bytes | None = None
    heartbeat_hits: int = 0
    state_json: bytes = json.dumps(
        {
            "mode": "HOVER",
            "arm": 1,
            "agl_mm": 420,
            "seen": 1,
            "cx": 160,
            "cy": 140,
        }
    ).encode("utf-8")


class FakePiHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/state":
            body = FakePiState.state_json
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if self.path == "/preset":
            FakePiState.last_preset_body = body
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            resp = b'{"ok":true}'
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return
        if self.path == "/heartbeat":
            FakePiState.heartbeat_hits += 1
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            resp = b'{"ok":true}'
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return
        if self.path == "/cmd":
            FakePiState.last_cmd_body = body
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            resp = b'{"ok":true}'
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return
        self.send_error(404)


@pytest.fixture()
def fake_pi():
    FakePiState.last_preset_body = None
    FakePiState.last_cmd_body = None
    FakePiState.heartbeat_hits = 0
    port = pick_ephemeral_port()
    httpd = HTTPServer(("127.0.0.1", port), FakePiHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    set_pi_http_port(port)
    try:
        yield f"127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
        set_pi_http_port(8766)


@pytest.fixture()
def desktop_server(fake_pi):
    host, _port = fake_pi.rsplit(":", 1)
    set_pi_host(host)
    port = pick_ephemeral_port()
    httpd = make_server("127.0.0.1", port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
        set_pi_host(None)


def _post(url: str, body: bytes) -> bytes:
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read()


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.read()


def test_preset_proxy_forwards_body_unchanged(desktop_server: str) -> None:
    preset = {
        "bias_roll_us": 1500,
        "bias_pitch_us": 1500,
        "bias_yaw_us": 1500,
        "bias_thrust_us": 1350,
        "yaw_max_us": 80,
        "yaw_slew_us_s": 400,
        "roll_max_us": 30,
        "roll_slew_us_s": 200,
        "pitch_min_us": 0,
        "pitch_max_us": 120,
        "pitch_slew_us_s": 300,
        "thrust_target_us": 40,
        "thrust_slew_us_s": 250,
        "hover_thrust_us": 1350,
        "hover_slew_us_s": 2500,
        "land_thrust_us": 1100,
        "land_slew_us_s": 2500,
    }
    raw = json.dumps(preset).encode("utf-8")
    _post(f"{desktop_server}/preset", raw)
    assert FakePiState.last_preset_body == raw


def test_heartbeat_proxy_reaches_pi(desktop_server: str) -> None:
    _post(f"{desktop_server}/heartbeat", b"{}")
    assert FakePiState.heartbeat_hits == 1


def test_cmd_proxy_forwards_disarm(desktop_server: str) -> None:
    raw = json.dumps({"cmd": "DISARM"}).encode("utf-8")
    _post(f"{desktop_server}/cmd", raw)
    assert FakePiState.last_cmd_body == raw


def test_state_proxy_returns_fake_body(desktop_server: str) -> None:
    body = _get(f"{desktop_server}/state")
    assert body == FakePiState.state_json


def test_state_without_pi_host_is_disconnected() -> None:
    set_pi_host(None)
    port = pick_ephemeral_port()
    httpd = make_server("127.0.0.1", port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _get(f"http://127.0.0.1:{port}/state")
        assert exc_info.value.code == 503
        payload = json.loads(exc_info.value.read().decode("utf-8"))
        assert payload == {"error": "disconnected"}
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
