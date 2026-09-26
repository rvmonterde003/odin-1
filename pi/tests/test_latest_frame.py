from odin_pi.latest_frame import LatestFrameSlot


def test_detect_observes_newest_frame_only():
    slot = LatestFrameSlot[bytes]()
    slot.publish(b"frame1")
    slot.publish(b"frame2")

    seen = slot.latest()
    assert seen is not None
    assert seen.sequence == 2
    assert seen.payload == b"frame2"

    # Simulate detect starting after two publishes; never observes frame1.
    last_seq = 0
    snap = slot.wait_latest(last_seq, timeout=0.01)
    assert snap is not None
    assert snap.sequence == 2
    assert snap.payload == b"frame2"

    observed: list[bytes] = []

    def detect_once():
        s = slot.latest()
        if s is not None:
            observed.append(s.payload)

    detect_once()
    assert observed == [b"frame2"]
