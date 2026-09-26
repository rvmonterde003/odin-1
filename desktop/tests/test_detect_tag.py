import cv2
import numpy as np

from detect_tag import detect_tag, make_detector, shoelace_area


def _marker() -> np.ndarray:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    marker = cv2.aruco.generateImageMarker(dictionary, 0, 80)
    canvas = np.full((640, 640), 255, dtype=np.uint8)
    canvas[280:360, 280:360] = marker
    return canvas


def test_finds_id_0_and_area():
    hit = detect_tag(_marker(), make_detector())
    assert hit.seen is True
    assert 300 <= hit.cx <= 340
    assert 300 <= hit.cy <= 340
    assert hit.area > 1000


def test_blank_is_a_miss():
    hit = detect_tag(np.full((640, 640), 255, dtype=np.uint8), make_detector())
    assert hit.seen is False
    assert hit.cx == 0 and hit.cy == 0 and hit.area == 0


def test_other_id_is_a_miss():
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    marker = cv2.aruco.generateImageMarker(dictionary, 1, 80)
    canvas = np.full((640, 640), 255, dtype=np.uint8)
    canvas[280:360, 280:360] = marker
    hit = detect_tag(canvas, make_detector())
    assert hit.seen is False


def test_shoelace_unit_square():
    corners = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
    assert shoelace_area(corners) == 100
