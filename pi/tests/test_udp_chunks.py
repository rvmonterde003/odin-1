import struct

from odin_pi.udp_chunks import CHUNK_PAYLOAD, pack_chunks


def test_pack_chunks_splits_payload():
    jpeg = b"x" * (CHUNK_PAYLOAD + 10)
    chunks = pack_chunks(9, 640, 640, jpeg)
    assert len(chunks) == 2
    magic, frame_id, index, count, width, height = struct.unpack_from("<4sIHHHH", chunks[0])
    assert magic == b"OJPG"
    assert frame_id == 9
    assert index == 0
    assert count == 2
    assert width == 640
    assert height == 640
    assert chunks[0][16:] == b"x" * CHUNK_PAYLOAD
    magic, frame_id, index, count, width, height = struct.unpack_from("<4sIHHHH", chunks[1])
    assert index == 1
    assert chunks[1][16:] == b"x" * 10
