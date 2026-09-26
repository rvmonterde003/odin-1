from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass
class DetectHit:
    seen: bool
    cx: int
    cy: int
    area: int
    corners: np.ndarray | None = None


def shoelace_area(corners: Any) -> int:
    pts = np.asarray(corners, dtype=float).reshape(-1, 2)
    x = pts[:, 0]
    y = pts[:, 1]
    twice = 0.0
    for i in range(len(x)):
        j = (i + 1) % len(x)
        twice += x[i] * y[j] - x[j] * y[i]
    return int(round(abs(twice) * 0.5))


def make_detector() -> Any:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    params = cv2.aruco.DetectorParameters()
    params.adaptiveThreshWinSizeMin = 13
    params.adaptiveThreshWinSizeMax = 13
    params.minMarkerPerimeterRate = 0.05
    return cv2.aruco.ArucoDetector(dictionary, params)


def detect_tag(gray: np.ndarray, detector: Any) -> DetectHit:
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    corners, ids, _rejected = detector.detectMarkers(gray)
    if ids is None:
        return DetectHit(False, 0, 0, 0, None)
    for marker_corners, marker_id in zip(corners, ids.flatten()):
        if int(marker_id) != 0:
            continue
        pts = marker_corners.reshape(-1, 2)
        cx = int(round(float(pts[:, 0].mean())))
        cy = int(round(float(pts[:, 1].mean())))
        return DetectHit(True, cx, cy, shoelace_area(marker_corners), marker_corners)
    return DetectHit(False, 0, 0, 0, None)
