from chunks import CHUNK_PAYLOAD, pack_chunks
from link import CommandSession
from video_hub import VideoHub


def test_hub_gap_on_partial_drop():
    session = CommandSession()
    hub = VideoHub(session)
    partial = pack_chunks(1, 640, 640, b"z" * (CHUNK_PAYLOAD + 4))
    hub.feed(partial[0])
    nxt = pack_chunks(2, 640, 640, b"\xff\xd8\xff\xd9")
    hub.feed(nxt[0])
    assert "PILOT DISARM 0 0 0 640 640" in session.lines
    assert hub.latest_jpeg() is None


def test_poll_gap_after_50ms():
    session = CommandSession()
    session.on_connect()
    session.on_cmd("FOLLOW", 640, 640)
    hub = VideoHub(session)
    hub.note_complete_for_test(640, 640, now=0.0)
    session.lines.clear()
    hub.poll_gap(0.05)
    assert session.lines == ["PILOT FOLLOW 0 0 0 640 640"]
