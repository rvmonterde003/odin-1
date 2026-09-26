from odin_pi.telemetry import SharedTelemetry


def test_state_json_top_level_defaults():
    t = SharedTelemetry()
    assert t.snapshot_json() == {
        "mode": "DISARMED",
        "arm": 0,
        "agl_mm": -1,
        "seen": 0,
        "cx": 0,
        "cy": 0,
    }


def test_state_json_merges_state_and_tag():
    t = SharedTelemetry()
    t.update_state_line("STATE CHASE 1 1500 1500 1350 1580 1200")
    t.update_tag(True, 160, 140)
    assert t.snapshot_json() == {
        "mode": "CHASE",
        "arm": 1,
        "agl_mm": 1200,
        "seen": 1,
        "cx": 160,
        "cy": 140,
    }
