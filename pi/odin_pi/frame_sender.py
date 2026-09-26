from __future__ import annotations

import logging
import os
from collections.abc import Callable

import numpy as np

from odin_pi.latest_frame import LatestFrameSlot
from odin_pi.udp_chunks import pack_chunks

logger = logging.getLogger(__name__)

_DEFAULT_PORT = 8765
_VALID_SIDES = frozenset({640, 960})


def read_stream_config() -> tuple[int, str, int]:
    host = os.environ.get("ODIN_DESKTOP_HOST", "").strip()
    if not host:
        logger.error("ODIN_DESKTOP_HOST is not set")
        raise SystemExit(1)
    try:
        side = int(os.environ.get("ODIN_FRAME_SIZE", "640"))
    except ValueError:
        logger.error("invalid ODIN_FRAME_SIZE")
        raise SystemExit(1)
    if side not in _VALID_SIDES:
        logger.error("ODIN_FRAME_SIZE must be 640 or 960, got %d", side)
        raise SystemExit(1)
    port = int(os.environ.get("ODIN_VIDEO_PORT", str(_DEFAULT_PORT)))
    return side, host, port


def send_latest(
    slot: LatestFrameSlot[np.ndarray],
    encode: Callable[[np.ndarray], bytes],
    send: Callable[[bytes], None],
    stop_event,
    max_frames: int | None = None,
) -> int:
    frame_id = 0
    encoded_count = 0
    last_sequence = 0

    while not stop_event.is_set():
        if max_frames is not None and encoded_count >= max_frames:
            break

        snap = slot.latest()
        if snap is None:
            stop_event.wait(0.05)
            continue
        if snap.sequence <= last_sequence:
            snap = slot.wait_latest(last_sequence, timeout=0.05)
            if snap is None:
                continue
        if snap.sequence <= last_sequence:
            continue

        gray = snap.payload
        height, width = gray.shape[:2]
        jpeg = encode(gray)
        frame_id += 1
        for datagram in pack_chunks(frame_id, width, height, jpeg):
            send(datagram)
        last_sequence = snap.sequence
        encoded_count += 1

    return encoded_count
