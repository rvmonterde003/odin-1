from __future__ import annotations

import struct
import threading
import time
from collections import deque

import cv2
import numpy as np

from chunks import Assembler
from link import CommandSession


class VideoHub:
    def __init__(
        self,
        session: CommandSession,
        frame_ready: threading.Condition | None = None,
    ) -> None:
        self._session = session
        self._frame_ready = frame_ready
        self._asm = Assembler()
        self._lock = threading.Lock()
        self._header_seen = False
        self._last_wh: tuple[int, int] | None = None
        self._last_complete_at: float | None = None
        self._last_gap_poll_at: float | None = None
        self._latest_jpeg: bytes | None = None
        self._pending_jpeg: bytes | None = None
        self._pending_wh: tuple[int, int] = (0, 0)
        self._pending_gen = 0
        self._display_jpeg: bytes | None = None
        self._display_gen = 0
        self._stream_cv = threading.Condition()
        self._frame_times: deque[float] = deque()

    def feed(self, datagram: bytes) -> None:
        frame, dropped = self._asm.push(datagram)
        if len(datagram) >= 16:
            self._header_seen = True
            _, _, _, _, width, height = struct.unpack_from("<4sIHHHH", datagram)
            if width and height:
                self._last_wh = (width, height)

        if dropped:
            if frame is not None:
                self._session.on_gap(frame.width, frame.height)
            elif self._asm.last_drop_size is not None:
                self._session.on_gap(*self._asm.last_drop_size)

        if frame is None:
            return

        img = cv2.imdecode(np.frombuffer(frame.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None or img.shape[1] != frame.width or img.shape[0] != frame.height:
            self._session.on_gap(frame.width, frame.height)
            return

        self._session.note_side(min(frame.width, frame.height))
        now = time.monotonic()
        with self._lock:
            self._last_wh = (frame.width, frame.height)
            self._last_complete_at = now
            self._last_gap_poll_at = None
            self._latest_jpeg = frame.jpeg
            self._pending_jpeg = frame.jpeg
            self._pending_wh = (frame.width, frame.height)
            self._pending_gen += 1
            self._frame_times.append(now)
            cutoff = now - 1.0
            while self._frame_times and self._frame_times[0] < cutoff:
                self._frame_times.popleft()

        if self._frame_ready is not None:
            with self._frame_ready:
                self._frame_ready.notify_all()

    def poll_gap(self, now: float) -> None:
        if not self._header_seen or self._last_wh is None or self._last_complete_at is None:
            return
        if now - self._last_complete_at < 0.05:
            return
        if self._last_gap_poll_at is not None and now - self._last_gap_poll_at < 0.05:
            return
        self._last_gap_poll_at = now
        w, h = self._last_wh
        self._session.on_gap(w, h)

    def video_fps(self) -> int:
        now = time.monotonic()
        cutoff = now - 1.0
        while self._frame_times and self._frame_times[0] < cutoff:
            self._frame_times.popleft()
        return len(self._frame_times)

    def latest_jpeg(self) -> bytes | None:
        return self._latest_jpeg

    def last_frame_size(self) -> tuple[int, int]:
        if self._last_wh is None:
            return (0, 0)
        return self._last_wh

    def note_complete_for_test(self, w: int, h: int, now: float) -> None:
        self._header_seen = True
        self._last_wh = (w, h)
        self._last_complete_at = now
        self._last_gap_poll_at = None

    def take_pending_frame(self) -> tuple[bytes | None, tuple[int, int], int]:
        with self._lock:
            return self._pending_jpeg, self._pending_wh, self._pending_gen

    def set_display_jpeg(self, jpeg: bytes) -> None:
        with self._lock:
            self._display_jpeg = jpeg
            self._display_gen += 1
        with self._stream_cv:
            self._stream_cv.notify_all()

    def wait_display(self, last_gen: int, timeout: float) -> tuple[bytes, int] | None:
        with self._lock:
            if self._display_gen != last_gen and self._display_jpeg is not None:
                return self._display_jpeg, self._display_gen
        with self._stream_cv:
            self._stream_cv.wait(timeout=timeout)
        with self._lock:
            if self._display_gen != last_gen and self._display_jpeg is not None:
                return self._display_jpeg, self._display_gen
        return None
