from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

import numpy as np

from odin_pi.detect import DetectResult, detect_loop, make_apriltag_detector
from odin_pi.http_server import start_http_server
from odin_pi.latest_frame import LatestFrameSlot
from odin_pi.stream import LatestOverlay, MjpegPublisher, overlay_from_corners
from odin_pi.tag_lines import PilotOutState
from odin_pi.telemetry import SharedTelemetry
from odin_pi.uart import UartBridge, UartPort, open_uart, start_uart_thread
from odin_pi.watchdog import PostWatchdog

logger = logging.getLogger(__name__)


@dataclass
class ServiceContext:
    telemetry: SharedTelemetry
    watchdog: PostWatchdog
    uart_bridge: UartBridge
    pilot: PilotOutState
    mjpeg: MjpegPublisher
    frame_slot: LatestFrameSlot[np.ndarray]
    stop_event: threading.Event = field(default_factory=threading.Event)


class OdinPiService:
    def __init__(self, uart: UartPort | None = None) -> None:
        self.telemetry = SharedTelemetry()
        self.watchdog = PostWatchdog()
        self.mjpeg = MjpegPublisher()
        self.overlay = LatestOverlay()
        self.frame_slot: LatestFrameSlot[np.ndarray] = LatestFrameSlot()
        self.stop_event = threading.Event()
        self.pilot = PilotOutState.create()
        uart_port = uart if uart is not None else open_uart()
        self.uart_bridge, self._uart_thread = start_uart_thread(
            uart_port, self.telemetry, self.watchdog, self.pilot, self.stop_event
        )
        self.ctx = ServiceContext(
            telemetry=self.telemetry,
            watchdog=self.watchdog,
            uart_bridge=self.uart_bridge,
            pilot=self.pilot,
            mjpeg=self.mjpeg,
            frame_slot=self.frame_slot,
            stop_event=self.stop_event,
        )
        self._http_server = None
        self._camera_thread: threading.Thread | None = None
        self._detect_thread: threading.Thread | None = None
    def _on_detect_pass(self, result: DetectResult, seq: int) -> None:
        line = self.pilot.apply_detection(result.seen, result.cx, result.cy, result.corners)
        self.uart_bridge.write_line(line)
        self.telemetry.update_tag(result.seen, result.cx, result.cy)
        self.overlay.set(overlay_from_corners(result.corners, result.seen))

    def start(self, *, enable_camera: bool = True, http_port: int = 8766) -> None:
        # First bytes on the wire are an explicit disarm, before any detect pass.
        self.uart_bridge.write_line(self.pilot.disarm_line())
        self._http_server = start_http_server(self.ctx, port=http_port)
        self._detect_thread = threading.Thread(
            target=detect_loop,
            kwargs={
                "frame_slot": self.frame_slot,
                "detector_factory": make_apriltag_detector,
                "on_pass_complete": self._on_detect_pass,
                "stop_event": self.stop_event,
            },
            name="detect",
            daemon=True,
        )
        self._detect_thread.start()
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
        if self._http_server is not None:
            self._http_server.shutdown()


def run_service() -> None:
    logging.basicConfig(level=logging.INFO)
    svc = OdinPiService()
    svc.start()
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        svc.stop()
