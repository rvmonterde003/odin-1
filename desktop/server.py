"""Desktop proxy and static UI for Odin-2 chase test."""

from __future__ import annotations

import http.client
import json
import mimetypes
import os
import socket
import threading
import urllib.error
import urllib.request
from urllib.parse import urlparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BIND_HOST = "127.0.0.1"
BIND_PORT = 8770
PI_HTTP_PORT = 8766  # overridden in tests via set_pi_http_port()

STATIC_DIR = Path(__file__).resolve().parent / "static"

pi_host: str | None = None
_pi_host_lock = threading.Lock()


def set_pi_http_port(port: int) -> None:
    global PI_HTTP_PORT
    PI_HTTP_PORT = port


def set_pi_host(host: str | None) -> None:
    with _pi_host_lock:
        global pi_host
        if host is None:
            pi_host = None
            return
        cleaned = host.strip()
        pi_host = cleaned if cleaned else None


def get_pi_host() -> str | None:
    with _pi_host_lock:
        return pi_host


def _pi_base() -> str | None:
    host = get_pi_host()
    if not host:
        return None
    return f"http://{host}:{PI_HTTP_PORT}"


# One persistent HTTP/1.1 connection to the Pi, reused across requests. The Pi
# Zero W cannot afford a new TCP connection and handler thread per poll.
_conn_lock = threading.Lock()
_conn: http.client.HTTPConnection | None = None
_conn_key: tuple[str, int] | None = None


def _drop_conn() -> None:
    global _conn, _conn_key
    if _conn is not None:
        try:
            _conn.close()
        except OSError:
            pass
    _conn = None
    _conn_key = None


def _resolve_ipv4(host: str) -> str:
    # Windows returns the Pi's IPv6 link-local address first for odin-1.local and
    # http.client tries it first, costing ~2 s or the whole timeout per connect.
    # The Pi server listens on IPv4 only, so connect to the IPv4 address.
    try:
        infos = socket.getaddrinfo(host, PI_HTTP_PORT, socket.AF_INET, socket.SOCK_STREAM)
        if infos:
            return infos[0][4][0]
    except OSError:
        pass
    return host


def _get_conn(host: str) -> http.client.HTTPConnection:
    global _conn, _conn_key
    key = (host, PI_HTTP_PORT)
    if _conn is None or _conn_key != key:
        _drop_conn()
        _conn = http.client.HTTPConnection(_resolve_ipv4(host), PI_HTTP_PORT, timeout=5)
        _conn_key = key
    return _conn


def _proxy_request(
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    host = get_pi_host()
    if not host:
        return (
            HTTPStatus.SERVICE_UNAVAILABLE,
            {"Content-Type": "application/json"},
            b'{"error":"disconnected"}',
        )

    send_headers = dict(headers or {})
    if body is not None and "Content-Type" not in send_headers:
        send_headers["Content-Type"] = "application/json"

    with _conn_lock:
        last_exc: Exception | None = None
        for attempt in range(2):
            conn = _get_conn(host)
            try:
                conn.request(method, path, body=body, headers=send_headers)
                resp = conn.getresponse()
                payload = resp.read()
                status = resp.status
                resp_headers = dict(resp.getheaders())
                if resp.getheader("Connection", "").lower() == "close" or resp.version < 11:
                    _drop_conn()
                break
            except (http.client.HTTPException, OSError) as exc:
                # Stale keep-alive or Pi restarted: reconnect once and retry.
                last_exc = exc
                _drop_conn()
        else:
            return (
                HTTPStatus.BAD_GATEWAY,
                {"Content-Type": "application/json"},
                b'{"error":"pi_unreachable"}',
            )

    out_headers: dict[str, str] = {}
    for key in ("Content-Type", "Content-Length"):
        if key in resp_headers:
            out_headers[key] = resp_headers[key]
    if "Content-Type" not in out_headers:
        out_headers["Content-Type"] = "application/json"
    if "Content-Length" not in out_headers:
        out_headers["Content-Length"] = str(len(payload))
    return status, out_headers, payload


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
        path = urlparse(self.path).path
        if path == "/state":
            status, headers, body = _proxy_request("GET", "/state")
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/stream":
            base = _pi_base()
            if base is None:
                self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"disconnected")
                return

            # IPv4 explicitly: see _resolve_ipv4. And read1() below returns whatever
            # has arrived instead of blocking for a full 64 KB block, which with
            # ~1 KB frames meant seconds of nothing, then a burst.
            url = f"http://{_resolve_ipv4(get_pi_host() or '')}:{PI_HTTP_PORT}/stream"
            try:
                req = urllib.request.Request(url)
                resp = urllib.request.urlopen(req, timeout=5)
            except OSError:
                self.send_response(HTTPStatus.BAD_GATEWAY)
                self.end_headers()
                return

            try:
                self.send_response(resp.status)
                for key in ("Content-Type", "Cache-Control", "Pragma"):
                    if key in resp.headers:
                        self.send_header(key, resp.headers[key])
                self.end_headers()
                while True:
                    chunk = resp.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            finally:
                resp.close()
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
        if self.path == "/connect":
            raw = self._read_body()
            try:
                data = json.loads(raw.decode("utf-8") if raw else "{}")
            except json.JSONDecodeError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                return
            set_pi_host(data.get("host"))
            # Connected means the Pi answered /state, not just that a host was typed.
            reachable = False
            if get_pi_host() is not None:
                status, _headers, _body = _proxy_request("GET", "/state")
                reachable = status == HTTPStatus.OK
            self._send_json(HTTPStatus.OK, {"ok": True, "connected": reachable})
            return

        if self.path == "/preset":
            body = self._read_body()
            status, headers, out = _proxy_request(
                "POST",
                "/preset",
                body=body,
                headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
            )
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(out)
            return

        if self.path == "/heartbeat":
            status, headers, out = _proxy_request("POST", "/heartbeat", body=b"{}", headers={"Content-Type": "application/json"})
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(out)
            return

        if self.path == "/cmd":
            body = self._read_body()
            status, headers, out = _proxy_request(
                "POST",
                "/cmd",
                body=body,
                headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
            )
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(out)
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
    httpd = make_server(host, port)
    print(f"Odin desktop UI http://{host}:{port}/")
    httpd.serve_forever()


def pick_ephemeral_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((BIND_HOST, 0))
        return sock.getsockname()[1]


if __name__ == "__main__":
    run()
