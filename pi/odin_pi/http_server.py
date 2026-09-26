from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from odin_pi.service import ServiceContext

BOUNDARY = b"frame"


class OdinHttpHandler(BaseHTTPRequestHandler):
    ctx: ServiceContext
    # HTTP/1.1 so the desktop proxy can hold one connection open. On a Pi Zero W
    # a new TCP connection plus a new handler thread per request cost more CPU
    # than the camera loop. Every response below sets Content-Length; /stream
    # sends Connection: close and is the only long-lived request.
    protocol_version = "HTTP/1.1"
    # Keep-alive without TCP_NODELAY stalls every small response by a delayed-ACK
    # round (200 ms on Windows). Measured 450 ms per heartbeat before this.
    disable_nagle_algorithm = True

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/stream":
            self._handle_stream()
            return
        if path == "/state":
            body = json.dumps(self.ctx.telemetry.snapshot_json()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def _handle_stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY.decode('ascii')}")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        last_generation = -1
        self.ctx.mjpeg.viewer_connected()
        try:
            while not self.ctx.stop_event.is_set():
                waited = self.ctx.mjpeg.wait_jpeg(last_generation, timeout=1.0)
                if waited is None:
                    continue
                jpeg, last_generation = waited
                try:
                    self.wfile.write(b"--" + BOUNDARY + b"\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
        finally:
            self.ctx.mjpeg.viewer_disconnected()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/cmd":
            from odin_pi.tag_lines import ALLOWED_DESKTOP_CMDS, normalize_desktop_cmd

            data = self._read_json_body()
            cmd = str(data.get("cmd", "")).upper()
            if cmd not in ALLOWED_DESKTOP_CMDS:
                self.send_error(400, "invalid cmd")
                return
            pilot_mode = normalize_desktop_cmd(cmd)
            if pilot_mode is None:
                self.send_error(400, "invalid cmd")
                return
            self.ctx.watchdog.notify_post()
            line = self.ctx.pilot.set_mode(pilot_mode)
            if pilot_mode == "HOVER":
                # Arming is only ever an explicit desktop key. The ESP32 arms on
                # CMD HOVER and never on a PILOT line.
                self.ctx.uart_bridge.write_line("CMD HOVER")
            self.ctx.uart_bridge.write_line(line)
            self._json_ok({"ok": True})
            return
        if path == "/heartbeat":
            # One round trip does both jobs: feeds the watchdog and returns the
            # state, so the desktop needs one request per tick, not two.
            self._read_json_body()
            self.ctx.watchdog.notify_post()
            self._json_ok(self.ctx.telemetry.snapshot_json())
            return
        if path == "/preset":
            from odin_pi.preset import Preset, preset_uart_lines

            data = self._read_json_body()
            preset = Preset.from_json(data)
            self.ctx.watchdog.notify_post()
            for line in preset_uart_lines(preset):
                self.ctx.uart_bridge.write_line(line)
            self._json_ok({"ok": True})
            return
        self.send_error(404)

    def _json_ok(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_http_server(ctx: "ServiceContext", host: str = "0.0.0.0", port: int = 8766) -> ThreadingHTTPServer:
    handler = type("Handler", (OdinHttpHandler,), {"ctx": ctx})
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, name="http", daemon=True)
    thread.start()
    return server
