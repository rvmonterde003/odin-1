# Desktop AprilTag Stream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Pi streams the newest center-square JPEG, this PC runs AprilTag 36h11 id 0, and the ESP32 takes pilot commands over the hotspot.

**Architecture:** UDP chunks carry one JPEG at a time into a desktop assembler. A detect thread reads only the newest complete frame. A command session turns keys, presets, gaps, and browser heartbeats into the existing ASCII lines and sends them on one TCP connection to the ESP32. The ESP32 parses those lines, runs the same chase law, and still owns CRSF and the VL53.

**Tech Stack:** Python 3, OpenCV ArUco, pytest, existing desktop `ThreadingHTTPServer`, picamera2 on the Pi, ESP-IDF Wi-Fi STA plus lwIP sockets.

## Global Constraints

- Printed tag stays AprilTag 36h11, id 0. No YOLO, no CUDA, no GPU path.
- Pi does not run AprilTag, does not open the ESP32 UART, and does not serve HTTP.
- Stream default is 640×640 at 30 fps. `ODIN_FRAME_SIZE` may be 640 or 960 only. Anything else: log and exit. No silent fallback.
- JPEG quality default 60. UDP port 8765. Chunk payload 1400 bytes. Header 16 bytes little-endian. Magic bytes `4F 4A 50 47`.
- A full chunk is 1416 bytes so it is not IP-fragmented.
- Desktop binds UDP `0.0.0.0:8765` and TCP-connects to the ESP32 on port 8771.
- `PILOT <mode> <cx> <cy> <area> <w> <h>`. A miss is `PILOT <mode> 0 0 0 <w> <h>`. `PILOT` never arms. Only `CMD HOVER` arms. The first line of every TCP session is `CMD DISARM`.
- `area_stop_px2` on the page stays in 320-pixel units. Sent value is `area_stop_px2 * (side / 320)^2`, rounded to nearest integer, halves away from zero. Do not scale deadband, slew, or stick gains.
- A discarded partial frame sends a miss immediately. No complete frame for 50 ms repeats the miss every 50 ms. Complete frames skipped because a newer complete frame is waiting do not send a miss.
- Browser posts `/heartbeat` every 200 ms. Desktop sends `PING` every 100 ms only while a browser heartbeat arrived in the last 1000 ms. After 1000 ms of browser silence, send `CMD DISARM` once and stop `PING`.
- ESP32 disarms when 500 ms pass with no byte received from the TCP client. Bytes the ESP32 writes do not refresh that timer.
- Wi-Fi SSID and password live only in gitignored `esp32/main/wifi_secrets.h`. Empty values: log, do not connect, stay disarmed.
- Do not flash the ESP32. Do not image the Pi. Props stay off.
- `main` is not modified. All work stays on `cursor/desktop-apriltag-stream-6133`.

---

### Task 1: JPEG chunk codec and assembler

**Files:**
- Create: `desktop/chunks.py`
- Create: `desktop/tests/test_chunks.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `MAGIC = b"OJPG"`
  - `CHUNK_PAYLOAD = 1400`
  - `pack_chunks(frame_id: int, width: int, height: int, jpeg: bytes) -> list[bytes]`
  - `Assembled` dataclass: `frame_id: int`, `width: int`, `height: int`, `jpeg: bytes`
  - `Assembler.push(datagram: bytes) -> tuple[Assembled | None, bool]` where the bool is true when a partial frame was discarded

- [ ] **Step 1: Write the failing test**

Create `desktop/tests/test_chunks.py`:

```python
from chunks import CHUNK_PAYLOAD, MAGIC, Assembler, pack_chunks


def test_pack_round_trip_one_chunk():
    jpeg = b"\xff\xd8" + b"a" * 20 + b"\xff\xd9"
    parts = pack_chunks(7, 640, 640, jpeg)
    assert len(parts) == 1
    asm = Assembler()
    frame, dropped = asm.push(parts[0])
    assert dropped is False
    assert frame is not None
    assert frame.frame_id == 7
    assert frame.width == 640
    assert frame.height == 640
    assert frame.jpeg == jpeg
    assert parts[0][:4] == MAGIC


def test_pack_splits_at_1400():
    jpeg = b"x" * (CHUNK_PAYLOAD + 10)
    parts = pack_chunks(1, 640, 640, jpeg)
    assert len(parts) == 2
    assert len(parts[0]) == 16 + CHUNK_PAYLOAD
    assert len(parts[1]) == 16 + 10
    asm = Assembler()
    first, dropped = asm.push(parts[1])
    assert first is None and dropped is False
    frame, dropped = asm.push(parts[0])
    assert dropped is False
    assert frame is not None and frame.jpeg == jpeg


def test_missing_chunk_does_not_publish():
    jpeg = b"y" * (CHUNK_PAYLOAD + 5)
    parts = pack_chunks(3, 640, 640, jpeg)
    asm = Assembler()
    frame, _ = asm.push(parts[0])
    assert frame is None


def test_new_frame_id_drops_partial_and_reports():
    jpeg = b"z" * (CHUNK_PAYLOAD + 5)
    old = pack_chunks(1, 640, 640, jpeg)
    new = pack_chunks(2, 960, 960, b"ok")
    asm = Assembler()
    asm.push(old[0])
    frame, dropped = asm.push(new[0])
    assert dropped is True
    assert frame is not None
    assert frame.frame_id == 2
    assert frame.jpeg == b"ok"


def test_repeat_of_complete_id_does_not_publish_again():
    jpeg = b"q" * 8
    parts = pack_chunks(4, 640, 640, jpeg)
    asm = Assembler()
    frame, _ = asm.push(parts[0])
    assert frame is not None
    again, dropped = asm.push(parts[0])
    assert again is None and dropped is False


def test_bad_magic_ignored():
    jpeg = b"q" * 8
    parts = pack_chunks(4, 640, 640, jpeg)
    bad = b"XXXX" + parts[0][4:]
    asm = Assembler()
    frame, dropped = asm.push(bad)
    assert frame is None and dropped is False
```

- [ ] **Step 2: Run test to verify it fails**

Run from `desktop/`: `python -m pytest -q tests/test_chunks.py`

Expected: FAIL, `chunks` not importable.

- [ ] **Step 3: Write minimal implementation**

Create `desktop/chunks.py`:

```python
from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"OJPG"
CHUNK_PAYLOAD = 1400
_HEADER = struct.Struct("<4sIHHHH")


def pack_chunks(frame_id: int, width: int, height: int, jpeg: bytes) -> list[bytes]:
    if not jpeg:
        raise ValueError("empty jpeg")
    if width <= 0 or height <= 0:
        raise ValueError("frame size")
    count = (len(jpeg) + CHUNK_PAYLOAD - 1) // CHUNK_PAYLOAD
    out: list[bytes] = []
    fid = frame_id & 0xFFFFFFFF
    for index in range(count):
        payload = jpeg[index * CHUNK_PAYLOAD : (index + 1) * CHUNK_PAYLOAD]
        out.append(_HEADER.pack(MAGIC, fid, index, count, width, height) + payload)
    return out


@dataclass(frozen=True)
class Assembled:
    frame_id: int
    width: int
    height: int
    jpeg: bytes


class Assembler:
    def __init__(self) -> None:
        self._id: int | None = None
        self._count = 0
        self._parts: dict[int, bytes] = {}
        self._w = 0
        self._h = 0
        self._done: int | None = None

    def push(self, datagram: bytes) -> tuple[Assembled | None, bool]:
        if len(datagram) < _HEADER.size:
            return None, False
        magic, frame_id, index, count, width, height = _HEADER.unpack_from(datagram)
        if magic != MAGIC or count == 0 or index >= count or width == 0 or height == 0:
            return None, False
        payload = datagram[_HEADER.size :]
        if index < count - 1 and len(payload) != CHUNK_PAYLOAD:
            return None, False
        if self._done == frame_id:
            return None, False
        dropped = False
        if self._id != frame_id:
            if self._id is not None and len(self._parts) < self._count:
                dropped = True
            self._id = frame_id
            self._count = count
            self._parts = {}
            self._w = width
            self._h = height
            self._done = None
        if count != self._count or width != self._w or height != self._h:
            return None, dropped
        self._parts[index] = payload
        if len(self._parts) != self._count:
            return None, dropped
        if any(i not in self._parts for i in range(self._count)):
            return None, dropped
        jpeg = b"".join(self._parts[i] for i in range(self._count))
        self._done = frame_id
        self._parts = {}
        return Assembled(frame_id, width, height, jpeg), dropped
```

- [ ] **Step 4: Run test to verify it passes**

Run from `desktop/`: `python -m pytest -q tests/test_chunks.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/chunks.py desktop/tests/test_chunks.py
git commit -m "Add the JPEG chunk assembler for the desktop video path."
```

### Task 2: Command session

**Files:**
- Create: `desktop/link.py`
- Create: `desktop/tests/test_link.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `scale_area_stop(area_stop_px2: int, side: int) -> int`
  - `format_safe_line(area_stop_px2: int, deadband_pct: int, lpf_ms: int, agl_ceiling_mm: int, side: int) -> str`
  - `format_pilot_line(mode: str, cx: int, cy: int, area: int, w: int, h: int) -> str`
  - `CommandSession` with `lines: list[str]`, `mode: str`, `on_connect()`, `on_cmd(cmd: str, w: int, h: int)`, `on_preset(preset: dict)`, `note_side(side: int)`, `on_gap(w: int, h: int)`, `on_detect(seen: bool, cx: int, cy: int, area: int, w: int, h: int)`, `on_browser_heartbeat(now: float)`, `poll(now: float)`

- [ ] **Step 1: Write the failing test**

Create `desktop/tests/test_link.py`:

```python
from link import CommandSession, format_safe_line, scale_area_stop


def test_scale_area_stop_320_and_640():
    assert scale_area_stop(1000, 320) == 1000
    assert scale_area_stop(1000, 640) == 4000
    assert format_safe_line(1000, 10, 150, 0, 640) == "SAFE 4000 10 150 0"


def test_safe_not_sent_before_side_known():
    session = CommandSession()
    session.on_connect()
    session.on_preset({"area_stop_px2": 1000, "deadband_pct": 10, "lpf_ms": 150, "agl_ceiling_mm": 0,
                       "bias_roll_us": 1500, "bias_pitch_us": 1500, "bias_yaw_us": 1500, "bias_thrust_us": 1350,
                       "yaw_max_us": 80, "roll_max_us": 30, "pitch_min_us": 0, "pitch_max_us": 120,
                       "thrust_target_us": 40, "yaw_slew_us_s": 400, "roll_slew_us_s": 200,
                       "pitch_slew_us_s": 300, "thrust_slew_us_s": 250,
                       "hover_thrust_us": 1350, "hover_slew_us_s": 2500, "land_thrust_us": 1100,
                       "land_slew_us_s": 2500, "action_thrust_us": 0, "action_slew_us_s": 250})
    assert not any(line.startswith("SAFE ") for line in session.lines)
    session.note_side(640)
    assert "SAFE 4000 10 150 0" in session.lines


def test_connect_starts_with_cmd_disarm():
    session = CommandSession()
    session.on_connect()
    assert session.lines[0] == "CMD DISARM"
    assert session.mode == "DISARM"


def test_hover_sends_cmd_then_pilot():
    session = CommandSession()
    session.on_connect()
    session.lines.clear()
    session.on_cmd("HOVER", 640, 640)
    assert session.lines[0] == "CMD HOVER"
    assert session.lines[1] == "PILOT HOVER 0 0 0 640 640"
    assert not any(line.startswith("PILOT") and "CMD" in line for line in session.lines)


def test_cmd_without_frame_size_skips_pilot():
    session = CommandSession()
    session.on_connect()
    session.lines.clear()
    session.on_cmd("HOVER", 0, 0)
    assert session.lines == ["CMD HOVER"]
    assert session.mode == "HOVER"


def test_escape_sends_pilot_disarm():
    session = CommandSession()
    session.on_connect()
    session.on_cmd("HOVER", 640, 640)
    session.lines.clear()
    session.on_cmd("DISARM", 640, 640)
    assert session.lines == ["PILOT DISARM 0 0 0 640 640"]
    assert session.mode == "DISARM"


def test_gap_writes_miss():
    session = CommandSession()
    session.on_connect()
    session.on_cmd("FOLLOW", 640, 640)
    session.lines.clear()
    session.on_gap(640, 640)
    assert session.lines == ["PILOT FOLLOW 0 0 0 640 640"]


def test_detect_hit_and_miss():
    session = CommandSession()
    session.on_connect()
    session.on_cmd("FOLLOW", 640, 640)
    session.lines.clear()
    session.on_detect(True, 100, 200, 50, 640, 640)
    session.on_detect(False, 0, 0, 0, 640, 640)
    assert session.lines == [
        "PILOT FOLLOW 100 200 50 640 640",
        "PILOT FOLLOW 0 0 0 640 640",
    ]


def test_browser_silence_disarms_and_stops_ping():
    session = CommandSession()
    session.on_connect()
    session.on_cmd("HOVER", 640, 640)
    session.on_browser_heartbeat(0.0)
    session.lines.clear()
    session.poll(0.05)
    assert session.lines == ["PING"]
    session.lines.clear()
    session.poll(1.05)
    assert session.lines == ["CMD DISARM"]
    session.lines.clear()
    session.poll(1.20)
    assert session.lines == []
```

- [ ] **Step 2: Run test to verify it fails**

Run from `desktop/`: `python -m pytest -q tests/test_link.py`

Expected: FAIL, `link` not importable.

- [ ] **Step 3: Write minimal implementation**

Create `desktop/link.py`. Preset field order must match `pi/odin_pi/preset.py`: BIAS is roll pitch yaw thrust; CHASE is yaw_max roll_max pitch_min pitch_max thrust_target then the four slews yaw roll pitch thrust; HTHR is hover_thrust hover_slew land_thrust land_slew action_thrust action_slew; SAFE is area deadband lpf ceiling.

```python
from __future__ import annotations

import math

PING_INTERVAL_S = 0.1
BROWSER_ALIVE_S = 1.0


def scale_area_stop(area_stop_px2: int, side: int) -> int:
    scaled = area_stop_px2 * (side / 320.0) ** 2
    if scaled >= 0:
        return int(math.floor(scaled + 0.5))
    return int(math.ceil(scaled - 0.5))


def format_pilot_line(mode: str, cx: int, cy: int, area: int, w: int, h: int) -> str:
    return f"PILOT {mode} {int(cx)} {int(cy)} {int(area)} {int(w)} {int(h)}"


def format_safe_line(area_stop_px2: int, deadband_pct: int, lpf_ms: int, agl_ceiling_mm: int, side: int) -> str:
    area = scale_area_stop(area_stop_px2, side)
    return f"SAFE {area} {int(deadband_pct)} {int(lpf_ms)} {int(agl_ceiling_mm)}"


def _bias(preset: dict) -> str:
    return "BIAS {bias_roll_us} {bias_pitch_us} {bias_yaw_us} {bias_thrust_us}".format(**preset)


def _chase(preset: dict) -> str:
    return (
        "CHASE {yaw_max_us} {roll_max_us} {pitch_min_us} {pitch_max_us} {thrust_target_us} "
        "{yaw_slew_us_s} {roll_slew_us_s} {pitch_slew_us_s} {thrust_slew_us_s}"
    ).format(**preset)


def _hthr(preset: dict) -> str:
    return (
        "HTHR {hover_thrust_us} {hover_slew_us_s} {land_thrust_us} {land_slew_us_s} "
        "{action_thrust_us} {action_slew_us_s}"
    ).format(**preset)


class CommandSession:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.mode = "DISARM"
        self.side: int | None = None
        self._preset: dict | None = None
        self._last_browser: float | None = None
        self._next_ping = 0.0
        self._silence_disarmed = False
        self._w = 0
        self._h = 0

    def on_connect(self) -> None:
        self.mode = "DISARM"
        self._silence_disarmed = False
        self._next_ping = 0.0
        self.lines.append("CMD DISARM")

    def note_side(self, side: int) -> None:
        if side <= 0:
            return
        changed = self.side != side
        self.side = side
        if changed and self._preset is not None:
            self.lines.append(self._safe())

    def on_preset(self, preset: dict) -> None:
        self._preset = dict(preset)
        self.lines.append(_bias(preset))
        self.lines.append(_chase(preset))
        self.lines.append(_hthr(preset))
        if self.side is not None:
            self.lines.append(self._safe())

    def _safe(self) -> str:
        assert self._preset is not None and self.side is not None
        return format_safe_line(
            int(self._preset["area_stop_px2"]),
            int(self._preset["deadband_pct"]),
            int(self._preset["lpf_ms"]),
            int(self._preset["agl_ceiling_mm"]),
            self.side,
        )

    def on_cmd(self, cmd: str, w: int, h: int) -> None:
        key = cmd.strip().upper()
        if key == "CHASE":
            key = "FOLLOW"
        self._w, self._h = w, h
        if key == "HOVER":
            self.mode = "HOVER"
            self.lines.append("CMD HOVER")
            if w > 0 and h > 0:
                self.lines.append(format_pilot_line("HOVER", 0, 0, 0, w, h))
            return
        if key in ("FOLLOW", "HOLD", "LAND", "DISARM"):
            self.mode = key
            if w > 0 and h > 0:
                self.lines.append(format_pilot_line(key, 0, 0, 0, w, h))

    def on_gap(self, w: int, h: int) -> None:
        self._w, self._h = w, h
        self.lines.append(format_pilot_line(self.mode, 0, 0, 0, w, h))

    def on_detect(self, seen: bool, cx: int, cy: int, area: int, w: int, h: int) -> None:
        self._w, self._h = w, h
        if not seen:
            self.lines.append(format_pilot_line(self.mode, 0, 0, 0, w, h))
            return
        self.lines.append(format_pilot_line(self.mode, cx, cy, area, w, h))

    def on_browser_heartbeat(self, now: float) -> None:
        self._last_browser = now
        self._silence_disarmed = False

    def poll(self, now: float) -> None:
        if self._last_browser is None:
            return
        if now - self._last_browser >= BROWSER_ALIVE_S:
            if not self._silence_disarmed:
                self.mode = "DISARM"
                self.lines.append("CMD DISARM")
                self._silence_disarmed = True
            return
        if now >= self._next_ping:
            self.lines.append("PING")
            self._next_ping = now + PING_INTERVAL_S
```

- [ ] **Step 4: Run test to verify it passes**

Run from `desktop/`: `python -m pytest -q tests/test_link.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/link.py desktop/tests/test_link.py
git commit -m "Add the desktop command session for ESP32 pilot lines."
```

### Task 3: AprilTag on one frame

**Files:**
- Create: `desktop/detect_tag.py`
- Create: `desktop/tests/test_detect_tag.py`
- Modify: `desktop/requirements.txt`

**Interfaces:**
- Consumes: nothing
- Produces: `DetectHit` with `seen: bool`, `cx: int`, `cy: int`, `area: int`, `corners`; `detect_tag(gray, detector) -> DetectHit`; `make_detector()`

- [ ] **Step 1: Add OpenCV and write the failing test**

`desktop/requirements.txt` becomes:

```text
pytest==8.3.4
opencv-python-headless==4.10.0.84
numpy==2.2.6
```

Install with `python -m pip install -r desktop/requirements.txt` before the test run.

Create `desktop/tests/test_detect_tag.py`:

```python
import cv2
import numpy as np

from detect_tag import detect_tag, make_detector, shoelace_area


def _marker() -> np.ndarray:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    marker = cv2.aruco.generateImageMarker(dictionary, 0, 80)
    canvas = np.full((640, 640), 255, dtype=np.uint8)
    canvas[280:360, 280:360] = marker
    return canvas


def test_finds_id_0_and_area():
    hit = detect_tag(_marker(), make_detector())
    assert hit.seen is True
    assert 300 <= hit.cx <= 340
    assert 300 <= hit.cy <= 340
    assert hit.area > 1000


def test_blank_is_a_miss():
    hit = detect_tag(np.full((640, 640), 255, dtype=np.uint8), make_detector())
    assert hit.seen is False
    assert hit.cx == 0 and hit.cy == 0 and hit.area == 0


def test_other_id_is_a_miss():
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    marker = cv2.aruco.generateImageMarker(dictionary, 1, 80)
    canvas = np.full((640, 640), 255, dtype=np.uint8)
    canvas[280:360, 280:360] = marker
    hit = detect_tag(canvas, make_detector())
    assert hit.seen is False


def test_shoelace_unit_square():
    corners = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
    assert shoelace_area(corners) == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run from `desktop/`: `python -m pytest -q tests/test_detect_tag.py`

Expected: FAIL, `detect_tag` not importable.

- [ ] **Step 3: Write minimal implementation**

Create `desktop/detect_tag.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass
class DetectHit:
    seen: bool
    cx: int
    cy: int
    area: int
    corners: np.ndarray | None = None


def shoelace_area(corners: Any) -> int:
    pts = np.asarray(corners, dtype=float).reshape(-1, 2)
    x = pts[:, 0]
    y = pts[:, 1]
    twice = 0.0
    for i in range(len(x)):
        j = (i + 1) % len(x)
        twice += x[i] * y[j] - x[j] * y[i]
    return int(round(abs(twice) * 0.5))


def make_detector() -> Any:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    params = cv2.aruco.DetectorParameters()
    params.adaptiveThreshWinSizeMin = 13
    params.adaptiveThreshWinSizeMax = 13
    params.minMarkerPerimeterRate = 0.05
    return cv2.aruco.ArucoDetector(dictionary, params)


def detect_tag(gray: np.ndarray, detector: Any) -> DetectHit:
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    corners, ids, _rejected = detector.detectMarkers(gray)
    if ids is None:
        return DetectHit(False, 0, 0, 0, None)
    for marker_corners, marker_id in zip(corners, ids.flatten()):
        if int(marker_id) != 0:
            continue
        pts = marker_corners.reshape(-1, 2)
        cx = int(round(float(pts[:, 0].mean())))
        cy = int(round(float(pts[:, 1].mean())))
        return DetectHit(True, cx, cy, shoelace_area(marker_corners), marker_corners)
    return DetectHit(False, 0, 0, 0, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run from `desktop/`: `python -m pytest -q tests/test_detect_tag.py`

Expected: PASS. If id 0 is not found because the generated marker is too small for the perimeter floor, drop `minMarkerPerimeterRate` only in the test image by drawing the marker larger (side 160, placed at 240,240). Do not relax the detector parameters. Those stay at window 13 and perimeter 0.05.

- [ ] **Step 5: Commit**

```bash
git add desktop/detect_tag.py desktop/tests/test_detect_tag.py desktop/requirements.txt
git commit -m "Run AprilTag 36h11 id 0 on desktop frames."
```

### Task 4: Desktop server and page

**Files:**
- Modify: `desktop/server.py`
- Modify: `desktop/static/index.html`
- Modify: `desktop/tests/test_proxy.py` (replace the Pi-proxy tests)
- Create: `desktop/video_hub.py`

**Interfaces:**
- Consumes: `Assembler`, `pack_chunks`, `CommandSession`, `detect_tag`, `make_detector`
- Produces: HTTP on `127.0.0.1:8770` with `/connect`, `/cmd`, `/preset`, `/heartbeat`, `/state`, `/stream`. `VideoHub.feed(datagram) -> None` updates the latest JPEG and calls `session.on_gap` or `session.note_side`. `VideoHub.latest_jpeg() -> bytes | None`.

The page label "Pi host" becomes "ESP32 host" (`id="esp_host"`). Subtitle becomes `640×640 AprilTag · this PC detects`. Connect posts `{ "host": "<esp host>" }`. The stream image still uses `/stream` plus a cache-busting query. The 200 ms tick still POSTs `/heartbeat` while connected. Keys stay H, 1, 2, L, Esc, with the same number-input guard. Status text uses `video_fps` when present: append ` · video <fps>`.

`server.py` stops proxying to the Pi. Delete `_proxy_request`, `_pi_base`, and `set_pi_host`. Keep `make_server`, `pick_ephemeral_port`, and `run`.

`VideoHub` behavior:
- `feed` calls `Assembler.push`.
- On a published frame, store the JPEG only after `cv2.imdecode` reports a size equal to the header. On a mismatch, call `session.on_gap(width, height)` and do not store it.
- On `dropped is True`, call `session.on_gap` with the new frame's width and height if a frame was also published, otherwise with the header width and height of the datagram that caused the drop. The assembler bool is enough: if `dropped` and a frame was published, gap uses that frame's size; if `dropped` and nothing was published, gap uses the size parsed from this datagram's header (call `on_gap` with the published frame's w/h when `frame` is not None, else skip size and use the last header the hub stored). Simplest rule that matches the tests below: if `dropped`, `session.on_gap(frame.width, frame.height)` when `frame` is not None; when `frame` is None, `session.on_gap` is still required, so `Assembler.push` must be extended in this task to return the discarded header size. Add `Assembler.last_drop_size -> tuple[int, int] | None`, set it whenever `dropped` becomes true, from the partial frame's stored `_w` and `_h` before resetting. `VideoHub` calls `session.on_gap(*asm.last_drop_size)`.
- Record arrival time of each published frame. `poll_gap(now)` calls `session.on_gap(last_w, last_h)` when `now - last_complete > 0.05` and a header has been seen. Repeat every 0.05 s while the gap continues.
- `video_fps` is published frames in the last 1 second.

Detect thread in `server.py`:
- Waits on a `threading.Condition` that `VideoHub` notifies when a new complete frame is stored.
- If several JPEGs arrived during a pass, decode only the newest. Do not call `on_gap` for those skipped complete frames.
- `cv2.imdecode`, then `detect_tag`. Call `session.on_detect`.
- Draw the box with `cv2.polylines` on a BGR copy only when `seen` and corners are not None, JPEG-encode that copy at quality 80, and store it as the display JPEG. The browser `/stream` serves the display JPEG, not the raw one.

TCP thread:
- Started by POST `/connect` with a non-empty host. Connect to `(host, 8771)` with `TCP_NODELAY`.
- On connect call `session.on_connect()` then write every queued line, each followed by `\n`.
- Loop: drain `session.lines` to the socket; `session.poll(time.monotonic())` every 20 ms; read available bytes and split on `\n`. Ignore `PONG`. A `STATE` line matches `^STATE (\S+) (\d+) (\d+) (\d+) (\d+) (\d+) (-?\d+)$` and updates mode, arm, roll, pitch, thr, yaw, agl_mm used by `/state`.
- `/state` `seen`, `cx`, `cy` come from the last `on_detect`, not from STATE.
- If the socket dies, `/state` reports `"esp": "disconnected"`. Do not auto-reconnect in this task. The operator presses Connect again.

POST `/heartbeat` calls `session.on_browser_heartbeat(time.monotonic())` and returns the same JSON as `/state`.

POST `/cmd` body `{"cmd": "HOVER"}` calls `session.on_cmd` with the last frame size. If no chunk header has arrived, pass `0, 0` so the session sends `CMD HOVER` and does not send a `PILOT` line. Same for FOLLOW, HOLD, LAND, and DISARM. Reject anything else with 400.

POST `/preset` calls `session.on_preset` with the JSON object. Unknown keys are ignored. Missing preset keys are filled from the same defaults as `pi/odin_pi/preset.py` `Preset`.

- [ ] **Step 1: Extend the assembler test for drop size, then implement `last_drop_size`**

Add to `desktop/tests/test_chunks.py`:

```python
def test_drop_records_partial_size():
    jpeg = b"z" * (CHUNK_PAYLOAD + 5)
    old = pack_chunks(1, 640, 640, jpeg)
    new = pack_chunks(2, 960, 960, b"ok")
    asm = Assembler()
    asm.push(old[0])
    asm.push(new[0])
    assert asm.last_drop_size == (640, 640)
```

Set `self.last_drop_size: tuple[int, int] | None = None` on the assembler. Assign it from `(self._w, self._h)` immediately before clearing the partial, and only when a partial was actually in progress.

- [ ] **Step 2: Write `desktop/video_hub.py` and `desktop/tests/test_video_hub.py`**

```python
def test_hub_gap_on_partial_drop():
    from chunks import pack_chunks, CHUNK_PAYLOAD
    from link import CommandSession
    from video_hub import VideoHub

    session = CommandSession()
    hub = VideoHub(session)
    partial = pack_chunks(1, 640, 640, b"z" * (CHUNK_PAYLOAD + 4))
    hub.feed(partial[0])
    nxt = pack_chunks(2, 640, 640, b"\xff\xd8\xff\xd9")
    hub.feed(nxt[0])
    assert "PILOT DISARM 0 0 0 640 640" in session.lines
```

The tiny JPEG will fail `imdecode` and must also produce a miss, not a stored frame. Assert `hub.latest_jpeg()` is None after that feed.

`poll_gap`:

```python
def test_poll_gap_after_50ms():
    session = CommandSession()
    session.on_connect()
    session.on_cmd("FOLLOW", 640, 640)
    hub = VideoHub(session)
    hub.note_complete_for_test(640, 640, now=0.0)
    session.lines.clear()
    hub.poll_gap(0.05)
    assert session.lines == ["PILOT FOLLOW 0 0 0 640 640"]
```

`note_complete_for_test` only exists so the timer can be tested without a real JPEG. It sets `_last_complete_at` and `_last_wh`.

- [ ] **Step 3: Replace `desktop/tests/test_proxy.py`**

Delete the fake Pi server. Keep one test that builds `make_server()`, calls `SESSION.note_side(640)` and records a last frame size of 640×640, clears `SESSION.lines`, then POSTs `/cmd` with `{"cmd":"HOVER"}` to the ephemeral port. Assert the lines are `CMD HOVER` then `PILOT HOVER 0 0 0 640 640`. Expose the session as `server.SESSION` created at import, and have the handler use that object. `/cmd` must emit `CMD HOVER` before the PILOT line. Add a second test: POST `/connect` with `{"host":""}` returns 200 and `{"ok": true, "connected": false}`.

- [ ] **Step 4: Implement `video_hub.py`, rewrite `server.py`, update `index.html`**

Follow the behavior in this task. `/stream` is multipart MJPEG, boundary `frame`, serving the latest display JPEG when the generation changes, same shape as `pi/odin_pi/http_server.py` `_handle_stream`. Ignore the query string on every path.

- [ ] **Step 5: Run desktop tests**

Run from `desktop/`: `python -m pytest -q`

Expected: PASS, including the old tests that were replaced and the new chunk, link, detect, and hub tests.

- [ ] **Step 6: Commit**

```bash
git add desktop/server.py desktop/video_hub.py desktop/chunks.py desktop/static/index.html desktop/tests
git commit -m "Serve detection and ESP32 commands from the desktop."
```

### Task 5: Pi capture sender

**Files:**
- Create: `pi/odin_pi/udp_chunks.py`
- Create: `pi/odin_pi/frame_sender.py`
- Modify: `pi/odin_pi/camera_worker.py`
- Modify: `pi/odin_pi/service.py`
- Create: `pi/tests/test_udp_chunks.py`
- Create: `pi/tests/test_frame_sender.py`

**Interfaces:**
- Consumes: `LatestFrameSlot`
- Produces: `pack_chunks` with the same header as `desktop/chunks.py`. `send_latest(slot, encode, send, stop_event, max_frames) -> int` returns how many frames were encoded. `read_stream_config() -> tuple[int, str, int]` returns `(side, desktop_host, port)` and raises `SystemExit` when the host is unset or the side is not 640 or 960.

- [ ] **Step 1: Write the failing tests**

`pi/tests/test_udp_chunks.py` packs a `CHUNK_PAYLOAD + 10` byte buffer and asserts two datagrams, magic `b"OJPG"`, frame id 9, indexes 0 then 1, chunk count 2, width 640, height 640, and payloads of 1400 and 10. Use `struct.unpack_from("<4sIHHHH", datagram)`.

`pi/tests/test_frame_sender.py`:

```python
import numpy as np

from odin_pi.frame_sender import send_latest
from odin_pi.latest_frame import LatestFrameSlot


def test_sender_encodes_only_the_later_frame():
    slot = LatestFrameSlot()
    slot.publish(np.zeros((8, 8), dtype=np.uint8))
    slot.publish(np.full((8, 8), 9, dtype=np.uint8))
    encoded: list[int] = []

    def encode(gray: np.ndarray) -> bytes:
        encoded.append(int(gray[0, 0]))
        return b"jpeg"

    sent: list[bytes] = []
    stop = __import__("threading").Event()
    n = send_latest(slot, encode, sent.append, stop, max_frames=1)
    assert n == 1
    assert encoded == [9]
    assert sent and sent[0].startswith(b"OJPG")
```

`send_latest` with `max_frames=1` encodes one newest frame and returns. It reads `slot.latest()` once at the start of each iteration and does not encode an older sequence.

Also test `read_stream_config` via `monkeypatch.setenv`. Unset `ODIN_DESKTOP_HOST` raises `SystemExit`. `ODIN_FRAME_SIZE=320` raises `SystemExit`. `ODIN_FRAME_SIZE=960` and `ODIN_DESKTOP_HOST=192.168.137.1` returns `(960, "192.168.137.1", 8765)`.

- [ ] **Step 2: Run the tests and confirm they fail**

Run from `pi/`: `python -m pytest -q tests/test_udp_chunks.py tests/test_frame_sender.py`

Expected: FAIL on import.

- [ ] **Step 3: Implement the sender and point the service at it**

`udp_chunks.py` is the same packing rules as `desktop/chunks.py`. Duplicate the function. Do not import from `desktop/`.

`camera_worker.py`: replace the fixed `FRAME_SIZE = (320, 320)` with the side from `ODIN_FRAME_SIZE` (default `"640"`). If the side is not 640 or 960, log and raise `SystemExit` before opening the camera. `extract_y_plane` uses that side, not 320. `TARGET_FPS` default becomes `"30"`. Leave the sensor mode and scaler crop as they are. `publish_camera_frame` may keep publishing a local JPEG; the service must not start the HTTP server, so that JPEG is unused. The frame slot payload is the gray array.

`service.py` becomes a camera thread plus a sender thread. Remove UART, HTTP, detect, watchdog, and pilot from `OdinPiService.start`. `run_service` calls `read_stream_config()`, opens a UDP socket, and sends to `(host, port)`. Encode with `cv2.imencode(".jpg", gray, [cv2.IMWRITE_JPEG_QUALITY, quality])` where quality is `ODIN_JPEG_QUALITY` default 60. The sender loop is `send_latest` without `max_frames` (run until `stop_event`).

Do not delete `detect.py`, `uart.py`, or `http_server.py`. Existing unit tests still import them. They are not started.

- [ ] **Step 4: Run Pi tests**

Run from `pi/`: `python -m pytest -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pi/odin_pi/udp_chunks.py pi/odin_pi/frame_sender.py pi/odin_pi/camera_worker.py pi/odin_pi/service.py pi/tests/test_udp_chunks.py pi/tests/test_frame_sender.py
git commit -m "Stream the newest square JPEG from the Pi."
```

### Task 6: ESP32 pilot line carries frame size

**Files:**
- Modify: `esp32/main/cmd_parser.c` (the `PILOT ` branch)
- Modify: `esp32/main/chase_test.c`

**Interfaces:**
- Consumes: `flight_state_t.tag` fields `cx`, `cy`, `area`, `w`, `h`, `seen`
- Produces: a `PILOT` line with fewer than six integers, or with `w` or `h` <= 0, leaves tag state unchanged. Otherwise stores `w` and `h` from the line.

- [ ] **Step 1: Add the chase case**

In `esp32/main/chase_test.c`, add `test_frame_size_center` and call it from `main` before the `chase ok` print:

```c
static int test_frame_size_center(void)
{
    chase_params_t p;
    hold_state_t hold;
    chase_params_set_defaults(&p);
    hold_state_init(&hold);
    p.area_stop_px2 = 1000;
    tag_state_t small = {.seen = 1, .cx = 160, .cy = 160, .w = 320, .h = 320, .area = 1000};
    int err = expect_sticks(ODIN_MODE_CHASE, &p, &small, &hold, 0,
                            1500, 1500, 1500, 1350, "center 320 stop");
    p.area_stop_px2 = 4000;
    tag_state_t big = {.seen = 1, .cx = 320, .cy = 320, .w = 640, .h = 640, .area = 4000};
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &big, &hold, 0,
                         1500, 1500, 1500, 1350, "center 640 stop");
    return err;
}
```

`tag_state_t.area` is the field to set. Do not change the stick law.

- [ ] **Step 2: Change the PILOT parser**

Replace the body of the `strncmp(p, "PILOT ", 6)` branch so it reads mode, cx, cy, area, w, h. On any missing field, or `w <= 0` or `h <= 0`, unlock and return without writing `s->tag`. On success:

```c
s->tag.cx = cx;
s->tag.cy = cy;
s->tag.area = area;
s->tag.w = w;
s->tag.h = h;
s->tag.seen = (cx != 0 || cy != 0 || area != 0) ? 1 : 0;
s->tag.last_ms = flight_now_ms();
```

Mode handling stays as it is now: `DISARM` always disarms; `HOVER`, `FOLLOW`, `HOLD`, and `LAND` change mode only when the current mode is not disarmed.

- [ ] **Step 3: Build the host chase test if `gcc` exists**

```bash
gcc -I esp32/main -o /tmp/chase_test esp32/main/chase_test.c esp32/main/chase.c
/tmp/chase_test
```

Expected: `chase ok`. If `gcc` is missing, say so in the commit message body and do not pretend the test ran.

- [ ] **Step 4: Commit**

```bash
git add esp32/main/cmd_parser.c esp32/main/chase_test.c
git commit -m "Accept frame width and height on PILOT lines."
```

### Task 7: ESP32 Wi-Fi command link

**Files:**
- Create: `esp32/main/wifi_link.c`
- Create: `esp32/main/wifi_link.h`
- Create: `esp32/main/wifi_secrets.example.h`
- Modify: `esp32/main/main.c`
- Modify: `esp32/main/CMakeLists.txt`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `cmd_parse_line`, `flight_state_*`, `odin_mode_str`, `PI_FAILSAFE_MS` (unchanged, 500)
- Produces: `void wifi_link_start(void)`. The CRSF task is unchanged and still calls `apply_pi_failsafe`.

- [ ] **Step 1: Secrets and gitignore**

Append `esp32/main/wifi_secrets.h` to `.gitignore`.

`wifi_secrets.example.h`:

```c
#pragma once
#define ODIN_WIFI_SSID ""
#define ODIN_WIFI_PASS ""
```

`wifi_link.c` includes `wifi_secrets.h`. Document in a comment at the top of `wifi_link.c`: copy the example to `wifi_secrets.h` and fill in the hotspot. Do not commit the filled file.

- [ ] **Step 2: Implement the link**

`wifi_link_start`:
- If `ODIN_WIFI_SSID` or `ODIN_WIFI_PASS` is an empty string, `ESP_LOGE` `"wifi not configured"` and return. Do not create the TCP task.
- Otherwise `xTaskCreatePinnedToCore` the link task on core 0, priority 5, stack 8192.
- The task initializes NVS, netif, the event loop, and a Wi-Fi station, then connects. On disconnect, call `esp_wifi_connect` again.
- After `IP_EVENT_STA_GOT_IP`, open a listening socket on port 8771, `SO_REUSEADDR`, backlog 1.
- Accept one client. If one is already open, `close` it first. Do not change `flight_state` mode in the accept path.
- Set `TCP_NODELAY` on the client.
- Read with a 20 ms `SO_RCVTIMEO`. Each received byte is appended to a line buffer. On `\n`, call `cmd_parse_line`. Any successful `recv` of length > 0 sets `last_pi_ms = flight_now_ms()` under the flight state lock. Do not set `last_pi_ms` when sending.
- Every 50 ms, if a client is connected, write `STATE %s %d %u %u %u %u %ld\n` using the same fields as `pi_uart.c` lines 75–88.
- `cmd_parse_line` may fill a reply (`PONG`). Write that reply if non-empty. Writing it must not refresh `last_pi_ms`.

`main.c`: remove `pi_uart_init` and the `pi_uart` task. Call `wifi_link_start()` after `flight_state_init`. Keep CRSF on core 1 and sensors on core 0.

`CMakeLists.txt`: replace `pi_uart.c` with `wifi_link.c`. Add `esp_wifi`, `esp_netif`, `esp_event`, and `nvs_flash` to `PRIV_REQUIRES`.

- [ ] **Step 3: Do not flash**

If `idf.py` is on `PATH`, run `idf.py build` in `esp32/` and expect `Project build complete`. If it is not installed, do not download the IDF and do not flash. Record that the build was not run.

- [ ] **Step 4: Commit**

```bash
git add esp32/main/wifi_link.c esp32/main/wifi_link.h esp32/main/wifi_secrets.example.h esp32/main/main.c esp32/main/CMakeLists.txt .gitignore
git commit -m "Take pilot commands over Wi-Fi instead of the Pi UART."
```

### Task 8: Handoff README

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: the behavior from Tasks 4, 5, and 7
- Produces: a handoff that matches this branch

- [ ] **Step 1: Rewrite the architecture paragraphs**

Replace the node diagram and the "who computes sticks" paragraphs so they say:

- The Pi captures a center square, default 640×640, and sends UDP JPEG chunks to `ODIN_DESKTOP_HOST` port 8765. It does not detect and it does not speak UART.
- This PC runs AprilTag and the page on `127.0.0.1:8770`. The page asks for the ESP32 host, not the Pi host.
- The ESP32 joins the hotspot and listens on TCP 8771. Copy `esp32/main/wifi_secrets.example.h` to `esp32/main/wifi_secrets.h` on the build machine. That file is gitignored.
- 500 ms of command-link silence still disarms. A dropped video frame clears the target and does not disarm.
- Do not flash unless asked. Props off.

Leave the wiring table, CRSF channel table, and the Betaflight warnings in place. Delete sentences that say the Pi runs AprilTag or that the desktop only proxies to port 8766.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Document the desktop AprilTag stream handoff."
```
