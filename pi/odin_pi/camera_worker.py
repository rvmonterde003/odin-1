from __future__ import annotations

import logging
import os
import time

import cv2
import numpy as np

from odin_pi.latest_frame import LatestFrameSlot
from odin_pi.stream import LatestOverlay, MjpegPublisher, gray_to_jpeg

logger = logging.getLogger(__name__)

# Spec target is 30. On a Pi Zero W (one ARMv6 core) libcamera's per-frame work
# costs about 2% CPU per fps, so 30 fps capture leaves nothing for the detector.
# Measured 25 Sep 2026: 30 fps = 64% CPU, 20 fps = 43%, 15 fps = 34%.
# ODIN_CAMERA_FPS overrides the default; the loop logs the rate it actually holds.
SPEC_FPS = 30
TARGET_FPS = int(os.environ.get("ODIN_CAMERA_FPS", "30"))


def _frame_side() -> int:
    try:
        side = int(os.environ.get("ODIN_FRAME_SIZE", "640"))
    except ValueError:
        logger.error("invalid ODIN_FRAME_SIZE")
        raise SystemExit(1)
    if side not in (640, 960):
        logger.error("ODIN_FRAME_SIZE must be 640 or 960, got %d", side)
        raise SystemExit(1)
    return side


_SIDE = _frame_side()
FRAME_SIZE = (_SIDE, _SIDE)

# IMX500 pixel array (ScalerCrop coordinates), not the active readout size.
PIXEL_ARRAY_W = 4056
PIXEL_ARRAY_H = 3040
SCALER_CROP_SIDE = 3040
SCALER_CROP_X = (PIXEL_ARRAY_W - SCALER_CROP_SIDE) // 2
SCALER_CROP_Y = 0


def publish_camera_frame(
    gray: np.ndarray,
    frame_slot: LatestFrameSlot[np.ndarray],
    mjpeg: MjpegPublisher,
    overlay: LatestOverlay,
) -> None:
    frame_slot.publish(gray)
    mjpeg.publish_jpeg(gray_to_jpeg(gray, overlay.current()))


def extract_y_plane(yuv420: np.ndarray) -> np.ndarray:
    """Y plane only: first side×side bytes of the YUV420 main buffer."""
    w, h = FRAME_SIZE
    flat = yuv420.reshape(-1)
    y = np.frombuffer(flat[: w * h], dtype=np.uint8)
    return y.reshape((h, w))


def camera_loop(
    frame_slot: LatestFrameSlot[np.ndarray],
    stop_event,
    mjpeg: MjpegPublisher,
    overlay: LatestOverlay,
    picamera2_module=None,
) -> None:
    """picamera2 is imported only inside this thread."""
    if picamera2_module is None:
        from picamera2 import Picamera2

        picamera2_module = Picamera2

    # One core: OpenCV's thread pool only adds scheduling overhead here.
    cv2.setNumThreads(1)
    frame_us = int(round(1_000_000 / TARGET_FPS))
    logger.info("camera target %d fps (spec %d)", TARGET_FPS, SPEC_FPS)
    picam2 = picamera2_module()
    config = picam2.create_video_configuration(
        sensor={"output_size": (2028, 1520), "bit_depth": 10},
        main={"size": FRAME_SIZE, "format": "YUV420"},
        controls={"FrameDurationLimits": (frame_us, frame_us)},
        buffer_count=4,
    )
    picam2.configure(config)
    picam2.set_controls(
        {"ScalerCrop": (SCALER_CROP_X, SCALER_CROP_Y, SCALER_CROP_SIDE, SCALER_CROP_SIDE)}
    )
    picam2.start()

    frame_count = 0
    t0 = time.monotonic()
    try:
        while not stop_event.is_set():
            request = picam2.capture_request()
            try:
                yuv = request.make_array("main")
                gray = extract_y_plane(yuv)
                if mjpeg.has_viewers():
                    publish_camera_frame(gray, frame_slot, mjpeg, overlay)
                else:
                    # Nobody is watching /stream: skip the JPEG encode (11 ms on a Zero W).
                    frame_slot.publish(gray)
            finally:
                request.release()

            frame_count += 1
            if frame_count % (TARGET_FPS * 5) == 0:
                elapsed = time.monotonic() - t0
                if elapsed > 0:
                    rate = frame_count / elapsed
                    logger.info(
                        "camera fps %.1f (target %d, viewers %d)",
                        rate, TARGET_FPS, mjpeg.viewer_count(),
                    )
                    frame_count = 0
                    t0 = time.monotonic()
    finally:
        picam2.stop()
