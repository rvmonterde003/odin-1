from odin_pi.preset import (
    Preset,
    format_bias_line,
    format_chase_line,
    format_hthr_line,
    format_safe_line,
    preset_uart_lines,
)


def test_default_preset_uart_lines_match_spec():
    p = Preset()
    assert format_bias_line(p) == "BIAS 1500 1500 1500 1350"
    assert format_chase_line(p) == "CHASE 80 30 0 120 40 400 200 300 250"
    assert format_hthr_line(p) == "HTHR 1350 2500 1100 2500 0 250"
    assert format_safe_line(p) == "SAFE 0 10 150 0"
    assert preset_uart_lines(p) == [
        "BIAS 1500 1500 1500 1350",
        "CHASE 80 30 0 120 40 400 200 300 250",
        "HTHR 1350 2500 1100 2500 0 250",
        "SAFE 0 10 150 0",
    ]


def test_preset_json_field_order_chase_line():
    data = {
        "bias_roll_us": 1500,
        "bias_pitch_us": 1500,
        "bias_yaw_us": 1500,
        "bias_thrust_us": 1350,
        "yaw_max_us": 80,
        "yaw_slew_us_s": 400,
        "roll_max_us": 30,
        "roll_slew_us_s": 200,
        "pitch_min_us": 0,
        "pitch_max_us": 120,
        "pitch_slew_us_s": 300,
        "thrust_target_us": 40,
        "thrust_slew_us_s": 250,
        "hover_thrust_us": 1400,
        "hover_slew_us_s": 2500,
        "land_thrust_us": 1100,
        "land_slew_us_s": 800,
    }
    lines = preset_uart_lines(Preset.from_json(data))
    assert lines[0] == "BIAS 1500 1500 1500 1350"
    assert lines[1] == "CHASE 80 30 0 120 40 400 200 300 250"
    assert lines[2] == "HTHR 1400 2500 1100 800 0 250"
    assert lines[3] == "SAFE 0 10 150 0"


def test_preset_safe_line_from_json():
    data = {"area_stop_px2": 4000, "deadband_pct": 8, "lpf_ms": 200, "agl_ceiling_mm": 1500}
    assert preset_uart_lines(Preset.from_json(data))[3] == "SAFE 4000 8 200 1500"
