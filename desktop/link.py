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
