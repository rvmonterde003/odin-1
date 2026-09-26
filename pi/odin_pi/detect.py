from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

import cv2
import numpy as np

logger = logging.getLogger(__name__)

ACCEPT_TAG_ID = 0


@dataclass
class DetectResult:
    seen: bool
    cx: int
    cy: int
    corners: np.ndarray | None = None


def make_apriltag_detector() -> Any:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    params = cv2.aruco.DetectorParameters()
    # Default adaptive thresholding runs three window sizes (3, 13, 23) per pass.
    # One window at 13 still finds the 36h11 tag at 40 px and 80 px on a 320x320
    # frame and cuts a pass from 266 ms to 97 ms on a Pi Zero W (measured
    # 25 Sep 2026 on a noisy synthetic frame). Perimeter floor 0.05 drops tiny
    # candidates; a tag still counts down to a 16 px side.
    params.adaptiveThreshWinSizeMin = 13
    params.adaptiveThreshWinSizeMax = 13
    params.minMarkerPerimeterRate = 0.05
    return cv2.aruco.ArucoDetector(dictionary, params)


def detect_tag_id0(gray: np.ndarray, detector: Any) -> DetectResult:
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    corners, ids, _rejected = detector.detectMarkers(gray)
    if ids is None:
        return DetectResult(seen=False, cx=0, cy=0, corners=None)
    for marker_corners, marker_id in zip(corners, ids.flatten()):
        if int(marker_id) != ACCEPT_TAG_ID:
            continue
        pts = marker_corners.reshape(-1, 2)
        cx = int(round(float(pts[:, 0].mean())))
        cy = int(round(float(pts[:, 1].mean())))
        return DetectResult(seen=True, cx=cx, cy=cy, corners=marker_corners)
    return DetectResult(seen=False, cx=0, cy=0, corners=None)


def detect_loop(
    frame_slot,
    detector_factory: Callable[[], Any],
    on_pass_complete: Callable[[DetectResult, int], None],
    stop_event,
) -> None:
    """Consume only the latest frame; never queue, never skip a finished result."""
    from odin_pi.latest_frame import LatestFrameSlot

    detector = detector_factory()
    last_seq = 0
    passes = 0
    t0 = time.monotonic()
    while not stop_event.is_set():
        snap = frame_slot.wait_latest(last_seq, timeout=0.05)
        if snap is None or snap.sequence <= last_seq:
            continue
        seq = snap.sequence
        gray = snap.payload
        result = detect_tag_id0(gray, detector)
        # Always report a finished pass. The next pass starts on the newest
        # frame anyway. Discarding a result because the camera published during
        # the pass burned the whole pass for nothing: at 20 fps on a Zero W that
        # dropped the reported rate to 2-6 passes/s while the thread ran at 40% CPU.
        last_seq = seq
        on_pass_complete(result, seq)
        passes += 1
        if passes == 1:
            t0 = time.monotonic()  # camera start-up lag is not detect time
        if passes == 26:
            elapsed = time.monotonic() - t0
            if elapsed > 0:
                logger.info("detect %.1f passes/s", (passes - 1) / elapsed)
            passes = 0
            t0 = time.monotonic()
