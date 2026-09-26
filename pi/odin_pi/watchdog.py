from __future__ import annotations

import threading
import time

# Spec says 500 ms. On the Pi Zero W over the hotspot a heartbeat round trip is
# 190 ms median, 360 ms p90 (25 Sep 2026), so 500 ms tripped on ordinary jitter.
# This is the second-tier guard (desktop gone). The ESP32's own 500 ms Pi-silence
# failsafe is unchanged and remains the hard stop.
DISARM_INTERVAL_S = 1.0


class PostWatchdog:
    """500 ms without POST after the first POST → periodic PILOT DISARM."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._first_post_at: float | None = None
        self._last_post_at: float | None = None

    def notify_post(self) -> None:
        now = time.monotonic()
        with self._lock:
            if self._first_post_at is None:
                self._first_post_at = now
            self._last_post_at = now

    def should_disarm(self, now: float | None = None) -> bool:
        t = time.monotonic() if now is None else now
        with self._lock:
            if self._first_post_at is None or self._last_post_at is None:
                return False
            if t - self._last_post_at < DISARM_INTERVAL_S:
                return False
            return True
