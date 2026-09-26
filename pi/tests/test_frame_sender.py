import numpy as np
import pytest

from odin_pi.frame_sender import read_stream_config, send_latest
from odin_pi.latest_frame import LatestFrameSlot


def test_sender_encodes_only_the_later_frame():
    slot = LatestFrameSlot()
    slot.publish(np.zeros((8, 8), dtype=np.uint8))
    slot.publish(np.full((8, 8), 9, dtype=np.uint8))
    encoded: list[int] = []

    def encode(gray: np.ndarray) -> bytes:
        encoded.append(int(gray[0, 0]))
        return b"jpeg"

    sent: list[bytes] = []
    stop = __import__("threading").Event()
    n = send_latest(slot, encode, sent.append, stop, max_frames=1)
    assert n == 1
    assert encoded == [9]
    assert sent and sent[0].startswith(b"OJPG")


def test_read_stream_config_requires_host(monkeypatch):
    monkeypatch.delenv("ODIN_DESKTOP_HOST", raising=False)
    monkeypatch.setenv("ODIN_FRAME_SIZE", "640")
    with pytest.raises(SystemExit):
        read_stream_config()


def test_read_stream_config_rejects_bad_side(monkeypatch):
    monkeypatch.setenv("ODIN_DESKTOP_HOST", "1.2.3.4")
    monkeypatch.setenv("ODIN_FRAME_SIZE", "320")
    with pytest.raises(SystemExit):
        read_stream_config()


def test_read_stream_config_ok(monkeypatch):
    monkeypatch.setenv("ODIN_DESKTOP_HOST", "192.168.137.1")
    monkeypatch.setenv("ODIN_FRAME_SIZE", "960")
    assert read_stream_config() == (960, "192.168.137.1", 8765)
