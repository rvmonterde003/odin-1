from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any

STATE_RE = re.compile(
    r"^STATE (?P<mode>\S+) (?P<arm>\d+) "
    r"(?P<roll>\d+) (?P<pitch>\d+) (?P<thr>\d+) (?P<yaw>\d+) (?P<agl>-?\d+)$"
)


@dataclass
class TagState:
    seen: int = 0
    cx: int = 0
    cy: int = 0
    w: int = 320
    h: int = 320


@dataclass
class SharedTelemetry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_state: dict[str, Any] | None = None
    last_tag: TagState = field(default_factory=TagState)
    last_pong_ms: float | None = None

    def update_state_line(self, line: str) -> None:
        m = STATE_RE.match(line.strip())
        if not m:
            return
        parsed = {
            "mode": m.group("mode"),
            "arm": int(m.group("arm")),
            "roll": int(m.group("roll")),
            "pitch": int(m.group("pitch")),
            "thr": int(m.group("thr")),
            "yaw": int(m.group("yaw")),
            "agl_mm": int(m.group("agl")),
        }
        with self.lock:
            self.last_state = parsed

    def update_tag(self, seen: bool, cx: int, cy: int) -> None:
        with self.lock:
            self.last_tag = TagState(
                seen=1 if seen else 0,
                cx=int(cx) if seen else 0,
                cy=int(cy) if seen else 0,
            )

    def snapshot_json(self) -> dict[str, Any]:
        with self.lock:
            if self.last_state is None:
                mode = "DISARMED"
                arm = 0
                agl_mm = -1
            else:
                mode = self.last_state["mode"]
                arm = self.last_state["arm"]
                agl_mm = self.last_state["agl_mm"]
            return {
                "mode": mode,
                "arm": arm,
                "agl_mm": agl_mm,
                "seen": self.last_tag.seen,
                "cx": self.last_tag.cx,
                "cy": self.last_tag.cy,
            }
