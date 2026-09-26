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


def test_connect_clears_preconnect_queue():
    session = CommandSession()
    session.lines.append("CMD HOVER")
    session.on_connect()
    assert session.take_lines() == ["CMD DISARM"]


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
