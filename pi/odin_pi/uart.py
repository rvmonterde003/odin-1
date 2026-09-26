from __future__ import annotations

import os
import threading
import time
from abc import ABC, abstractmethod
class UartPort(ABC):
    @abstractmethod
    def write_line(self, line: str) -> None: ...

    @abstractmethod
    def read_lines(self) -> list[str]: ...

    @abstractmethod
    def close(self) -> None: ...


class FakeUart(UartPort):
    """In-memory UART for unit tests and dev on Windows."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.written: list[str] = []
        self._inbound: list[str] = []

    def write_line(self, line: str) -> None:
        with self._lock:
            self.written.append(line)

    def feed_line(self, line: str) -> None:
        with self._lock:
            self._inbound.append(line)

    def read_lines(self) -> list[str]:
        with self._lock:
            lines = list(self._inbound)
            self._inbound.clear()
            return lines

    def close(self) -> None:
        pass


class SerialUart(UartPort):
    def __init__(self, device: str, baud: int = 115200) -> None:
        import serial

        self._ser = serial.Serial(device, baudrate=baud, timeout=0)
        self._buf = bytearray()

    def write_line(self, line: str) -> None:
        self._ser.write((line.rstrip("\n") + "\n").encode("ascii"))

    def read_lines(self) -> list[str]:
        chunk = self._ser.read(4096)
        if chunk:
            self._buf.extend(chunk)
        lines: list[str] = []
        while True:
            idx = self._buf.find(b"\n")
            if idx < 0:
                break
            raw = bytes(self._buf[:idx]).decode("ascii", errors="ignore").strip()
            del self._buf[: idx + 1]
            if raw:
                lines.append(raw)
        return lines

    def close(self) -> None:
        self._ser.close()


def open_uart(device: str | None = None) -> UartPort:
    dev = device if device is not None else os.environ.get("ODIN_UART", "/dev/serial0")
    if dev.lower() == "fake":
        return FakeUart()
    return SerialUart(dev)


class UartBridge:
    """Background reader/writer: PING, parse STATE/PONG, apply POST watchdog."""

    def __init__(
        self,
        uart: UartPort,
        telemetry: "SharedTelemetry",
        watchdog: "PostWatchdog",
        pilot: "PilotOutState",
        stop_event: threading.Event,
    ) -> None:
        self._uart = uart
        self._telemetry = telemetry
        self._watchdog = watchdog
        self._pilot = pilot
        self._stop = stop_event
        self._out_lock = threading.Lock()

    def write_line(self, line: str) -> None:
        with self._out_lock:
            self._uart.write_line(line)

    def run(self) -> None:
        next_ping = time.monotonic()
        next_watchdog = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_ping:
                self.write_line("PING")
                next_ping = now + 1.0

            if now >= next_watchdog and self._watchdog.should_disarm(now):
                self.write_line(self._pilot.disarm_line())
                next_watchdog = now + 0.5

            for line in self._uart.read_lines():
                if line == "PONG":
                    self._telemetry.last_pong_ms = time.monotonic() * 1000.0
                elif line.startswith("STATE "):
                    self._telemetry.update_state_line(line)

            time.sleep(0.01)

        self._uart.close()


def start_uart_thread(
    uart: UartPort,
    telemetry,
    watchdog,
    pilot,
    stop_event: threading.Event,
) -> tuple[UartBridge, threading.Thread]:
    bridge = UartBridge(uart, telemetry, watchdog, pilot, stop_event)
    thread = threading.Thread(target=bridge.run, name="uart", daemon=True)
    thread.start()
    return bridge, thread
