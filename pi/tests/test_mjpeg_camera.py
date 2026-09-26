import numpy as np

from odin_pi.camera_worker import publish_camera_frame
from odin_pi.latest_frame import LatestFrameSlot
from odin_pi.stream import LatestOverlay, MjpegPublisher


def test_two_camera_frames_bump_jpeg_generation_without_detect():
    slot: LatestFrameSlot[np.ndarray] = LatestFrameSlot()
    mjpeg = MjpegPublisher()
    overlay = LatestOverlay()

    gray1 = np.zeros((320, 320), dtype=np.uint8)
    gray2 = np.full((320, 320), 42, dtype=np.uint8)

    assert mjpeg.generation == 0
    publish_camera_frame(gray1, slot, mjpeg, overlay)
    assert mjpeg.generation == 1
    publish_camera_frame(gray2, slot, mjpeg, overlay)
    assert mjpeg.generation == 2

    latest = slot.latest()
    assert latest is not None
    assert latest.sequence == 2
    assert latest.payload[0, 0] == 42
