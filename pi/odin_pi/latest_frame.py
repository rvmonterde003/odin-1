from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class FrameSnapshot(Generic[T]):
    sequence: int
    payload: T


class LatestFrameSlot(Generic[T]):
    """Single-slot publisher: readers always see the newest frame only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sequence = 0
        self._payload: T | None = None
        self._cond = threading.Condition(self._lock)

    @property
    def sequence(self) -> int:
        with self._lock:
            return self._sequence

    def publish(self, payload: T) -> int:
        with self._cond:
            self._sequence += 1
            self._payload = payload
            self._cond.notify_all()
            return self._sequence

    def latest(self) -> FrameSnapshot[T] | None:
        with self._lock:
            if self._payload is None:
                return None
            return FrameSnapshot(sequence=self._sequence, payload=self._payload)

    def wait_latest(self, after_sequence: int, timeout: float | None = 0.05) -> FrameSnapshot[T] | None:
        with self._cond:
            while self._sequence <= after_sequence:
                if not self._cond.wait(timeout=timeout):
                    return None
            return FrameSnapshot(sequence=self._sequence, payload=self._payload)  # type: ignore[arg-type]

    def is_stale(self, sequence: int) -> bool:
        with self._lock:
            return sequence != self._sequence
