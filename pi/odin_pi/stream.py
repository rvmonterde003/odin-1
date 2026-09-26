from __future__ import annotations

import os
import threading
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class OverlayBox:
    seen: bool = False
    x1: int = 0
    y1: int = 0
    x2: int = 0
    y2: int = 0


class LatestOverlay:
    """Written by the detect thread; read when encoding each camera frame."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._box = OverlayBox(seen=False)

    def set(self, box: OverlayBox) -> None:
        with self._lock:
            self._box = box

    def current(self) -> OverlayBox:
        with self._lock:
            return OverlayBox(
                seen=self._box.seen,
                x1=self._box.x1,
                y1=self._box.y1,
                x2=self._box.x2,
                y2=self._box.y2,
            )


class MjpegPublisher:
    """Latest JPEG bytes for multipart /stream."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._generation = 0
        self._cond = threading.Condition(self._lock)
        self._viewers = 0

    def viewer_connected(self) -> None:
        with self._lock:
            self._viewers += 1

    def viewer_disconnected(self) -> None:
        with self._lock:
            self._viewers = max(0, self._viewers - 1)

    def viewer_count(self) -> int:
        with self._lock:
            return self._viewers

    def has_viewers(self) -> bool:
        return self.viewer_count() > 0

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def publish_jpeg(self, jpeg: bytes) -> None:
        with self._cond:
            self._jpeg = jpeg
            self._generation += 1
            self._cond.notify_all()

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    def wait_jpeg(self, after_generation: int = -1, timeout: float = 1.0) -> tuple[bytes, int] | None:
        with self._cond:
            while self._jpeg is None or self._generation <= after_generation:
                if not self._cond.wait(timeout=timeout):
                    return None
            return self._jpeg, self._generation


# Stream-only knobs. Detection never sees the stream, so these cannot change
# what the ESP32 gets; they only trade picture quality for CPU on the Pi.
# ODIN_STREAM_QUALITY: JPEG quality 1..100 (default 80).
# ODIN_STREAM_SCALE: 1 = full 320x320, 2 = 160x160 stream (default 1).
STREAM_QUALITY = max(1, min(100, int(os.environ.get("ODIN_STREAM_QUALITY", "80"))))
STREAM_SCALE = 2 if os.environ.get("ODIN_STREAM_SCALE", "1") == "2" else 1


def gray_to_jpeg(gray: np.ndarray, overlay: OverlayBox | None) -> bytes:
    # Encode the Y plane as a single-channel JPEG. The GRAY2BGR expansion plus
    # 3-channel encode cost 24.5 ms on a Zero W; grayscale direct is 11 ms.
    # The tag box is therefore white (255) over a black outline, not green.
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    if STREAM_SCALE == 2:
        vis = cv2.resize(gray, (gray.shape[1] // 2, gray.shape[0] // 2), interpolation=cv2.INTER_AREA)
    else:
        vis = gray.copy()
    if overlay is not None and overlay.seen:
        k = STREAM_SCALE
        p1 = (overlay.x1 // k, overlay.y1 // k)
        p2 = (overlay.x2 // k, overlay.y2 // k)
        cv2.rectangle(vis, p1, p2, 0, 4 // k)
        cv2.rectangle(vis, p1, p2, 255, 2 // k)
    ok, buf = cv2.imencode(".jpg", vis, [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_QUALITY])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


def overlay_from_corners(corners: np.ndarray | None, seen: bool) -> OverlayBox:
    if not seen or corners is None:
        return OverlayBox(seen=False)
    pts = corners.reshape(-1, 2)
    x1 = int(pts[:, 0].min())
    y1 = int(pts[:, 1].min())
    x2 = int(pts[:, 0].max())
    y2 = int(pts[:, 1].max())
    return OverlayBox(seen=True, x1=x1, y1=y1, x2=x2, y2=y2)
