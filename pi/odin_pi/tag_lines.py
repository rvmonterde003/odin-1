from __future__ import annotations



import threading

from dataclasses import dataclass

from typing import Any



import numpy as np



FRAME_W = 320

FRAME_H = 320



DESKTOP_CMD_TO_PILOT: dict[str, str] = {

    "HOVER": "HOVER",

    "HOLD": "HOLD",

    "FOLLOW": "FOLLOW",

    "CHASE": "FOLLOW",

    "LAND": "LAND",

    "DISARM": "DISARM",

}



ALLOWED_DESKTOP_CMDS = frozenset(DESKTOP_CMD_TO_PILOT.keys())





def normalize_desktop_cmd(cmd: str) -> str | None:

    key = cmd.strip().upper()

    return DESKTOP_CMD_TO_PILOT.get(key)





def quadrilateral_area_px(corners: Any) -> int:

    """Shoelace area of four tag corners in pixels, rounded to an integer."""

    pts = np.asarray(corners, dtype=float).reshape(-1, 2)

    x = pts[:, 0]

    y = pts[:, 1]

    n = len(x)

    twice = 0.0

    for i in range(n):

        j = (i + 1) % n

        twice += x[i] * y[j] - x[j] * y[i]

    return int(round(abs(twice) * 0.5))





def format_pilot_line(mode: str, seen: bool, cx: int, cy: int, area: int) -> str:

    pilot_mode = mode.strip().upper()

    if not seen:

        return f"PILOT {pilot_mode} 0 0 0"

    return f"PILOT {pilot_mode} {int(cx)} {int(cy)} {int(area)}"





def pilot_line_from_detection(mode: str, seen: bool, cx: int, cy: int, corners: Any | None) -> str:

    if not seen or corners is None:

        return format_pilot_line(mode, False, 0, 0, 0)

    area = quadrilateral_area_px(corners)

    return format_pilot_line(mode, True, cx, cy, area)





@dataclass

class PilotOutState:

    """Thread-safe pilot mode and last detection for immediate PILOT resends."""



    lock: threading.Lock

    # Boot mode is DISARM. HOVER here armed the aircraft on every service start,
    # because each detect pass sends PILOT <mode> and the ESP32 arms on PILOT HOVER.
    mode: str = "DISARM"

    seen: bool = False

    cx: int = 0

    cy: int = 0

    area: int = 0



    @classmethod

    def create(cls) -> PilotOutState:

        return cls(lock=threading.Lock())



    def set_mode(self, mode: str) -> str:

        with self.lock:

            self.mode = mode.strip().upper()

            return format_pilot_line(self.mode, self.seen, self.cx, self.cy, self.area)



    def apply_detection(

        self, seen: bool, cx: int, cy: int, corners: Any | None

    ) -> str:

        with self.lock:

            self.seen = seen

            if seen and corners is not None:

                self.cx = int(cx)

                self.cy = int(cy)

                self.area = quadrilateral_area_px(corners)

            else:

                self.seen = False

                self.cx = 0

                self.cy = 0

                self.area = 0

            return format_pilot_line(self.mode, self.seen, self.cx, self.cy, self.area)



    def disarm_line(self) -> str:

        with self.lock:

            self.mode = "DISARM"

            self.seen = False

            self.cx = 0

            self.cy = 0

            self.area = 0

            return format_pilot_line("DISARM", False, 0, 0, 0)


