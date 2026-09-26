from __future__ import annotations

import logging
import os
import socket
import threading

import cv2
import numpy as np

from odin_pi.frame_sender import read_stream_config, send_latest
from odin_pi.latest_frame import LatestFrameSlot
from odin_pi.stream import LatestOverlay, MjpegPublisher

logger = logging.getLogger(__name__)


class OdinPiService:
    def __init__(self) -> None:
        self.mjpeg = MjpegPublisher()
        self.overlay = LatestOverlay()
        self.frame_slot: LatestFrameSlot[np.ndarray] = LatestFrameSlot()
        self.stop_event = threading.Event()
        self._camera_thread: threading.Thread | None = None
        self._sender_thread: threading.Thread | None = None

    def start(
        self,
        *,
        enable_camera: bool = True,
        encode=None,
        send=None,
    ) -> None:
        if encode is None or send is None:
            raise ValueError("encode and send are required")

        self._sender_thread = threading.Thread(
            target=send_latest,
            kwargs={
                "slot": self.frame_slot,
                "encode": encode,
                "send": send,
                "stop_event": self.stop_event,
            },
            name="sender",
            daemon=True,
        )
        self._sender_thread.start()

        if enable_camera:
            from odin_pi.camera_worker import camera_loop

            self._camera_thread = threading.Thread(
                target=camera_loop,
                kwargs={
                    "frame_slot": self.frame_slot,
                    "stop_event": self.stop_event,
                    "mjpeg": self.mjpeg,
                    "overlay": self.overlay,
                },
                name="camera",
                daemon=True,
            )
            self._camera_thread.start()

    def stop(self) -> None:
        self.stop_event.set()


def run_service() -> None:
    logging.basicConfig(level=logging.INFO)
    _side, host, port = read_stream_config()
    quality = int(os.environ.get("ODIN_JPEG_QUALITY", "60"))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest = (host, port)
    logger.info("streaming JPEG to %s:%d (quality %d)", host, port, quality)

    def send(datagram: bytes) -> None:
        sock.sendto(datagram, dest)

    def encode(gray: np.ndarray) -> bytes:
        ok, buf = cv2.imencode(".jpg", gray, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            raise RuntimeError("jpeg encode failed")
        return buf.tobytes()

    svc = OdinPiService()
    svc.start(encode=encode, send=send)
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        svc.stop()
