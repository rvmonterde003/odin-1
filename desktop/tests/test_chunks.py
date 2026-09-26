from chunks import CHUNK_PAYLOAD, MAGIC, Assembler, pack_chunks


def test_pack_round_trip_one_chunk():
    jpeg = b"\xff\xd8" + b"a" * 20 + b"\xff\xd9"
    parts = pack_chunks(7, 640, 640, jpeg)
    assert len(parts) == 1
    asm = Assembler()
    frame, dropped = asm.push(parts[0])
    assert dropped is False
    assert frame is not None
    assert frame.frame_id == 7
    assert frame.width == 640
    assert frame.height == 640
    assert frame.jpeg == jpeg
    assert parts[0][:4] == MAGIC


def test_pack_splits_at_1400():
    jpeg = b"x" * (CHUNK_PAYLOAD + 10)
    parts = pack_chunks(1, 640, 640, jpeg)
    assert len(parts) == 2
    assert len(parts[0]) == 16 + CHUNK_PAYLOAD
    assert len(parts[1]) == 16 + 10
    asm = Assembler()
    first, dropped = asm.push(parts[1])
    assert first is None and dropped is False
    frame, dropped = asm.push(parts[0])
    assert dropped is False
    assert frame is not None and frame.jpeg == jpeg


def test_missing_chunk_does_not_publish():
    jpeg = b"y" * (CHUNK_PAYLOAD + 5)
    parts = pack_chunks(3, 640, 640, jpeg)
    asm = Assembler()
    frame, _ = asm.push(parts[0])
    assert frame is None


def test_new_frame_id_drops_partial_and_reports():
    jpeg = b"z" * (CHUNK_PAYLOAD + 5)
    old = pack_chunks(1, 640, 640, jpeg)
    new = pack_chunks(2, 960, 960, b"ok")
    asm = Assembler()
    asm.push(old[0])
    frame, dropped = asm.push(new[0])
    assert dropped is True
    assert frame is not None
    assert frame.frame_id == 2
    assert frame.jpeg == b"ok"


def test_repeat_of_complete_id_does_not_publish_again():
    jpeg = b"q" * 8
    parts = pack_chunks(4, 640, 640, jpeg)
    asm = Assembler()
    frame, _ = asm.push(parts[0])
    assert frame is not None
    again, dropped = asm.push(parts[0])
    assert again is None and dropped is False


def test_complete_frame_then_new_id_not_dropped():
    jpeg1 = b"\xff\xd8" + b"a" * 8 + b"\xff\xd9"
    jpeg2 = b"\xff\xd8" + b"b" * 8 + b"\xff\xd9"
    parts1 = pack_chunks(1, 640, 640, jpeg1)
    parts2 = pack_chunks(2, 640, 640, jpeg2)
    asm = Assembler()
    frame1, dropped1 = asm.push(parts1[0])
    assert dropped1 is False
    assert frame1 is not None and frame1.frame_id == 1
    frame2, dropped2 = asm.push(parts2[0])
    assert dropped2 is False
    assert frame2 is not None and frame2.frame_id == 2 and frame2.jpeg == jpeg2


def test_drop_records_partial_size():
    jpeg = b"z" * (CHUNK_PAYLOAD + 5)
    old = pack_chunks(1, 640, 640, jpeg)
    new = pack_chunks(2, 960, 960, b"ok")
    asm = Assembler()
    asm.push(old[0])
    asm.push(new[0])
    assert asm.last_drop_size == (640, 640)


def test_bad_magic_ignored():
    jpeg = b"q" * 8
    parts = pack_chunks(4, 640, 640, jpeg)
    bad = b"XXXX" + parts[0][4:]
    asm = Assembler()
    frame, dropped = asm.push(bad)
    assert frame is None and dropped is False
