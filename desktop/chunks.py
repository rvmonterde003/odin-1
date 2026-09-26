from __future__ import annotations

import struct
from dataclasses import dataclass

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


@dataclass(frozen=True)
class Assembled:
    frame_id: int
    width: int
    height: int
    jpeg: bytes


class Assembler:
    def __init__(self) -> None:
        self._id: int | None = None
        self._count = 0
        self._parts: dict[int, bytes] = {}
        self._w = 0
        self._h = 0
        self._done: int | None = None

    def push(self, datagram: bytes) -> tuple[Assembled | None, bool]:
        if len(datagram) < _HEADER.size:
            return None, False
        magic, frame_id, index, count, width, height = _HEADER.unpack_from(datagram)
        if magic != MAGIC or count == 0 or index >= count or width == 0 or height == 0:
            return None, False
        payload = datagram[_HEADER.size :]
        if index < count - 1 and len(payload) != CHUNK_PAYLOAD:
            return None, False
        if self._done == frame_id:
            return None, False
        dropped = False
        if self._id != frame_id:
            if self._id is not None and len(self._parts) < self._count:
                dropped = True
            self._id = frame_id
            self._count = count
            self._parts = {}
            self._w = width
            self._h = height
            self._done = None
        if count != self._count or width != self._w or height != self._h:
            return None, dropped
        self._parts[index] = payload
        if len(self._parts) != self._count:
            return None, dropped
        if any(i not in self._parts for i in range(self._count)):
            return None, dropped
        jpeg = b"".join(self._parts[i] for i in range(self._count))
        self._done = frame_id
        self._parts = {}
        return Assembled(frame_id, width, height, jpeg), dropped
