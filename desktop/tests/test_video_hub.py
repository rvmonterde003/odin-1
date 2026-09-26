import time

import cv2
import numpy as np

from chunks import CHUNK_PAYLOAD, pack_chunks
from link import CommandSession
from video_hub import VideoHub


def _tiny_jpeg() -> bytes:
    ok, enc = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    return enc.tobytes()


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


def test_epoch_tracks_frame_and_gap_miss():
    session = CommandSession()
    hub = VideoHub(session)
    jpeg = _tiny_jpeg()
    for part in pack_chunks(1, 8, 8, jpeg):
        hub.feed(part)
    _, wh, gen, ep = hub.take_pending_frame()
    assert wh == (8, 8)
    assert gen == 1
    assert hub.epoch() == ep
    epoch_at_store = ep
    time.sleep(0.06)
    session.lines.clear()
    hub.poll_gap(time.monotonic())
    assert session.lines
    assert hub.epoch() > epoch_at_store
