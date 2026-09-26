from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass
class Preset:
    bias_roll_us: int = 1500
    bias_pitch_us: int = 1500
    bias_yaw_us: int = 1500
    bias_thrust_us: int = 1350
    yaw_max_us: int = 80
    yaw_slew_us_s: int = 400
    roll_max_us: int = 30
    roll_slew_us_s: int = 200
    pitch_min_us: int = 0
    pitch_max_us: int = 120
    pitch_slew_us_s: int = 300
    thrust_target_us: int = 40
    thrust_slew_us_s: int = 250
    hover_thrust_us: int = 1350
    hover_slew_us_s: int = 2500
    land_thrust_us: int = 1100
    land_slew_us_s: int = 2500
    action_thrust_us: int = 0
    action_slew_us_s: int = 250
    # Safety / smoothing. 0 disables area_stop, lpf and the ceiling.
    area_stop_px2: int = 0
    deadband_pct: int = 10
    lpf_ms: int = 150
    agl_ceiling_mm: int = 0

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Preset:
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if f.name in data:
                kwargs[f.name] = int(data[f.name])
        return cls(**kwargs)


def format_bias_line(preset: Preset) -> str:
    return (
        f"BIAS {preset.bias_roll_us} {preset.bias_pitch_us} "
        f"{preset.bias_yaw_us} {preset.bias_thrust_us}"
    )


def format_chase_line(preset: Preset) -> str:
    """Field order: yaw_max roll_max pitch_min pitch_max thr_target yaw_slew roll_slew pitch_slew thr_slew."""
    return (
        f"CHASE {preset.yaw_max_us} {preset.roll_max_us} "
        f"{preset.pitch_min_us} {preset.pitch_max_us} {preset.thrust_target_us} "
        f"{preset.yaw_slew_us_s} {preset.roll_slew_us_s} {preset.pitch_slew_us_s} "
        f"{preset.thrust_slew_us_s}"
    )


def format_hthr_line(preset: Preset) -> str:
    """Field order: hover_thrust hover_slew land_thrust land_slew action_thrust action_slew."""
    return (
        f"HTHR {preset.hover_thrust_us} {preset.hover_slew_us_s} "
        f"{preset.land_thrust_us} {preset.land_slew_us_s} "
        f"{preset.action_thrust_us} {preset.action_slew_us_s}"
    )


def format_safe_line(preset: Preset) -> str:
    """Field order: area_stop_px2 deadband_pct lpf_ms agl_ceiling_mm."""
    return (
        f"SAFE {preset.area_stop_px2} {preset.deadband_pct} "
        f"{preset.lpf_ms} {preset.agl_ceiling_mm}"
    )


def preset_uart_lines(preset: Preset) -> list[str]:
    return [
        format_bias_line(preset),
        format_chase_line(preset),
        format_hthr_line(preset),
        format_safe_line(preset),
    ]
