from __future__ import annotations

import struct

MAGIC = b"OJPG"
CHUNK_PAYLOAD = 1400
_HEADER = struct.Struct("<4sIHHHH")


def pack_chunks(frame_id: int, width: int, height: int, jpeg: bytes) -> list[bytes]:
    if not jpeg:
        raise ValueError("empty jpeg")
    if width <= 0 or height <= 0:
        raise ValueError("frame size")
    count = (len(jpeg) + CHUNK_PAYLOAD - 1) // CHUNK_PAYLOAD
    out: list[bytes] = []
    fid = frame_id & 0xFFFFFFFF
    for index in range(count):
        payload = jpeg[index * CHUNK_PAYLOAD : (index + 1) * CHUNK_PAYLOAD]
        out.append(_HEADER.pack(MAGIC, fid, index, count, width, height) + payload)
    return out
