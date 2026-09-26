"""Desktop UI, video assembly, tag detection, and ESP32 command link."""

from __future__ import annotations

import json
import mimetypes
import re
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import cv2
import numpy as np

from detect_tag import detect_tag, make_detector
from link import CommandSession
from video_hub import VideoHub

BIND_HOST = "127.0.0.1"
BIND_PORT = 8770
UDP_PORT = 8765
ESP_TCP_PORT = 8771
STREAM_BOUNDARY = b"frame"

STATIC_DIR = Path(__file__).resolve().parent / "static"

STATE_RE = re.compile(
    r"^STATE (\S+) (\d+) (\d+) (\d+) (\d+) (\d+) (-?\d+)$"
)

PRESET_DEFAULTS: dict[str, int] = {
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
    "action_thrust_us": 0,
    "action_slew_us_s": 250,
    "area_stop_px2": 0,
    "deadband_pct": 10,
    "lpf_ms": 150,
    "agl_ceiling_mm": 0,
}

ALLOWED_CMDS = frozenset({"HOVER", "FOLLOW", "HOLD", "LAND", "DISARM"})

_frame_ready = threading.Condition()
SESSION = CommandSession()
HUB = VideoHub(SESSION, frame_ready=_frame_ready)

_state_lock = threading.Lock()
_esp_connected = False
_esp_mode = "DISARM"
_esp_arm = 0
_esp_roll = 0
_esp_pitch = 0
_esp_thr = 0
_esp_yaw = 0
_esp_agl_mm = 0
_detect_seen = 0
_detect_cx = 0
_detect_cy = 0

_tcp_thread: threading.Thread | None = None
_tcp_stop = threading.Event()
_udp_started = False
_bg_threads_lock = threading.Lock()


def _merge_preset(data: dict[str, Any]) -> dict[str, int]:
    out = dict(PRESET_DEFAULTS)
    for key in PRESET_DEFAULTS:
        if key in data:
            out[key] = int(data[key])
    return out


def _build_state() -> dict[str, Any]:
    with _state_lock:
        state: dict[str, Any] = {
            "mode": _esp_mode,
            "arm": _esp_arm,
            "roll": _esp_roll,
            "pitch": _esp_pitch,
            "thr": _esp_thr,
            "yaw": _esp_yaw,
            "agl_mm": _esp_agl_mm,
            "seen": _detect_seen,
            "cx": _detect_cx,
            "cy": _detect_cy,
            "esp": "connected" if _esp_connected else "disconnected",
        }
    fps = HUB.video_fps()
    if fps > 0:
        state["video_fps"] = fps
    return state


def _on_detect(seen: bool, cx: int, cy: int, area: int, w: int, h: int) -> None:
    global _detect_seen, _detect_cx, _detect_cy
    with _state_lock:
        _detect_seen = 1 if seen else 0
        _detect_cx = cx
        _detect_cy = cy
    SESSION.on_detect(seen, cx, cy, area, w, h)


def _detect_loop() -> None:
    detector = make_detector()
    last_gen = 0
    while True:
        with _frame_ready:
            _frame_ready.wait(timeout=1.0)
        jpeg, wh, gen = HUB.take_pending_frame()
        if jpeg is None or gen == last_gen:
            continue
        while True:
            jpeg2, wh2, gen2 = HUB.take_pending_frame()
            if gen2 == gen:
                break
            jpeg, wh, gen = jpeg2, wh2, gen2
        last_gen = gen
        w, h = wh
        arr = np.frombuffer(jpeg, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        hit = detect_tag(gray, detector)
        _on_detect(hit.seen, hit.cx, hit.cy, hit.area, w, h)
        display = bgr
        if hit.seen and hit.corners is not None:
            pts = np.asarray(hit.corners, dtype=np.int32).reshape(-1, 1, 2)
            cv2.polylines(display, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
        ok, enc = cv2.imencode(".jpg", display, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            HUB.set_display_jpeg(enc.tobytes())


def _udp_loop() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    while True:
        data, _addr = sock.recvfrom(65535)
        HUB.feed(data)


def _ensure_background_threads() -> None:
    global _udp_started
    with _bg_threads_lock:
        if _udp_started:
            return
        _udp_started = True
        threading.Thread(target=_udp_loop, daemon=True, name="udp-video").start()
        threading.Thread(target=_detect_loop, daemon=True, name="detect").start()


def _tcp_worker(host: str) -> None:
    global _esp_connected, _esp_mode, _esp_arm, _esp_roll, _esp_pitch, _esp_thr, _esp_yaw, _esp_agl_mm
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(5.0)
        sock.connect((host, ESP_TCP_PORT))
        sock.settimeout(0.02)
        with _state_lock:
            _esp_connected = True
        SESSION.on_connect()
        buf = b""
        next_poll = time.monotonic()
        while not _tcp_stop.is_set():
            for line in SESSION.take_lines():
                sock.sendall(line.encode("utf-8") + b"\n")
            now = time.monotonic()
            if now >= next_poll:
                SESSION.poll(now)
                HUB.poll_gap(now)
                next_poll = now + 0.02
            try:
                chunk = sock.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8", errors="replace").strip()
                if not text or text == "PONG":
                    continue
                m = STATE_RE.match(text)
                if m:
                    with _state_lock:
                        _esp_mode = m.group(1)
                        _esp_arm = int(m.group(2))
                        _esp_roll = int(m.group(3))
                        _esp_pitch = int(m.group(4))
                        _esp_thr = int(m.group(5))
                        _esp_yaw = int(m.group(6))
                        _esp_agl_mm = int(m.group(7))
    except OSError:
        pass
    finally:
        with _state_lock:
            _esp_connected = False
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _start_tcp(host: str) -> bool:
    global _tcp_thread
    _tcp_stop.set()
    if _tcp_thread is not None and _tcp_thread.is_alive():
        _tcp_thread.join(timeout=2)
    _tcp_stop.clear()
    _tcp_thread = threading.Thread(target=_tcp_worker, args=(host,), daemon=True, name="esp-tcp")
    _tcp_thread.start()
    time.sleep(0.05)
    with _state_lock:
        return _esp_connected


class DesktopHandler(BaseHTTPRequestHandler):
    server_version = "OdinDesktop/1.0"
    disable_nagle_algorithm = True

    def log_message(self, format: str, *args) -> None:
        pass

    def _send_json(self, status: int, obj: object) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else b""

    def do_GET(self) -> None:
        _ensure_background_threads()
        path = urlparse(self.path).path
        if path == "/state":
            self._send_json(HTTPStatus.OK, _build_state())
            return

        if path == "/stream":
            self.send_response(HTTPStatus.OK)
            self.send_header(
                "Content-Type",
                f"multipart/x-mixed-replace; boundary={STREAM_BOUNDARY.decode('ascii')}",
            )
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            last_gen = -1
            try:
                while True:
                    waited = HUB.wait_display(last_gen, timeout=1.0)
                    if waited is None:
                        continue
                    jpeg, last_gen = waited
                    try:
                        self.wfile.write(b"--" + STREAM_BOUNDARY + b"\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        break
            except OSError:
                pass
            return

        if path in ("/", "/index.html"):
            self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return

        if path.startswith("/static/"):
            rel = path[len("/static/") :]
            target = (STATIC_DIR / rel).resolve()
            if not str(target).startswith(str(STATIC_DIR.resolve())):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if target.is_file():
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                self._serve_file(target, ctype)
                return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        _ensure_background_threads()
        path = urlparse(self.path).path
        if path == "/connect":
            raw = self._read_body()
            try:
                data = json.loads(raw.decode("utf-8") if raw else "{}")
            except json.JSONDecodeError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                return
            host = str(data.get("host", "")).strip()
            connected = False
            if host:
                connected = _start_tcp(host)
            self._send_json(HTTPStatus.OK, {"ok": True, "connected": connected})
            return

        if path == "/preset":
            raw = self._read_body()
            try:
                data = json.loads(raw.decode("utf-8") if raw else "{}")
            except json.JSONDecodeError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                return
            if not isinstance(data, dict):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                return
            SESSION.on_preset(_merge_preset(data))
            self._send_json(HTTPStatus.OK, {"ok": True})
            return

        if path == "/heartbeat":
            SESSION.on_browser_heartbeat(time.monotonic())
            self._send_json(HTTPStatus.OK, _build_state())
            return

        if path == "/cmd":
            raw = self._read_body()
            try:
                data = json.loads(raw.decode("utf-8") if raw else "{}")
            except json.JSONDecodeError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                return
            cmd = str(data.get("cmd", "")).upper()
            if cmd not in ALLOWED_CMDS:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_cmd"})
                return
            w, h = HUB.last_frame_size()
            SESSION.on_cmd(cmd, w, h)
            self._send_json(HTTPStatus.OK, {"ok": True})
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def _serve_file(self, path: Path, content_type: str) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def make_server(
    host: str = BIND_HOST,
    port: int = BIND_PORT,
    handler: type[BaseHTTPRequestHandler] = DesktopHandler,
) -> ThreadingHTTPServer:
    class _ReusableHTTPServer(ThreadingHTTPServer):
        allow_reuse_address = True

    return _ReusableHTTPServer((host, port), handler)


def run(host: str = BIND_HOST, port: int = BIND_PORT) -> None:
    _ensure_background_threads()
    httpd = make_server(host, port)
    print(f"Odin desktop UI http://{host}:{port}/")
    httpd.serve_forever()


def pick_ephemeral_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((BIND_HOST, 0))
        return sock.getsockname()[1]


if __name__ == "__main__":
    run()
