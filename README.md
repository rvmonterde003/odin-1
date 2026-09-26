# Odin-2

Indoor AprilTag chase test for the KD aircraft. This PC runs AprilTag detection and sends keys and presets. The Pi captures and streams video. The ESP32 turns targets into CRSF sticks. This folder is the whole flight stack for that test.

`SPEC.md` is the numeric contract. `UNDERSTANDING.md` is the original brief. This file is the handoff for another machine. Where they disagree, the code and the notes below are the later truth. A few older sentences in `SPEC.md` still say `CMD` or `STATE CHASE`; the wire format is `PILOT` and the mode string is `FOLLOW`.

Do not modify the sibling repos `full-autonomous` or `base-tracking`. Do not copy optical-flow `pos_hold` into this tree. Props stay off until a bench failsafe check. Do not flash the ESP32 until asked. Betaflight stays in ANGLE. AUX2 POSHOLD stays low. Failsafe stage 2 on the FC should be Drop. CRSF from the ESP32 is TX-only, so the FC will not see a radio failsafe by itself.

## What is running now

The flight computer in the airframe is a **Raspberry Pi Zero W** (Nanya DRAM on the board), not a Pi Zero 2 W. It is 32-bit only (`armv6l`). Raspberry Pi OS Lite 32-bit (Debian Trixie) is the image that boots. The 64-bit Lite image does not boot this board (green LED flashes 7 times: kernel not found).

The camera is the official **Raspberry Pi AI Camera, Sony IMX500**. It is used as a normal camera. AprilTag runs on this PC with OpenCV ArUco, not on the Pi and not on the IMX500 neural processor.

As of 2026-09-25 on the bench PC:

- Pi hostname `odin-1`, user `odin-1`.
- It joins this PC's hotspot SSID `VINCENTzypher`. The hotspot must stay **WPA2 only**. The Zero W cannot join WPA3.
- Last address was `192.168.137.7`. DHCP can change it. The name is `odin-1.local`. Prefer the IPv4 address. Windows often resolves the name to IPv6 link-local first, and that path does not reach the Pi.
- SSH is on. Wi-Fi power save is off (`wifi.powersave = 2` and `iw dev wlan0 set power_save off`).
- The Pi UART to the ESP32 is not used by this branch. The wiring may still be present on the bench. `enable_uart=1` and `dtoverlay=disable-bt` remain in `/boot/firmware/config.txt` from earlier work.
- Camera auto-detect does not see the IMX500 on this Zero W. `/boot/firmware/config.txt` has `camera_auto_detect` commented out and `dtoverlay=imx500` set. After that, `rpicam-hello --list-cameras` shows `imx500 [4056x3040]`. The camera RP2040 firmware was already version 15. Do not reflash that firmware.
- Packages on the Pi: `imx500-all`, `imx500-firmware`, `python3-picamera2`, `iw`. Code lives at `/home/odin-1/odin-2/pi`. systemd unit `odin-pi.service` is enabled. Set `ODIN_DESKTOP_HOST` to this PC's hotspot IPv4 in the unit environment or shell profile; without it the service exits.
- The camera target is **30 fps** (`ODIN_CAMERA_FPS`, default 30). On a loaded Zero W the measured loop rate may be lower. The desktop assembles the UDP JPEG stream and runs detection on the newest complete frame.
- The ESP32 firmware has been built (`idf.py build` completed) and **has not been flashed**. Plug the ESP32 in only when asked, props off.

## Nodes

```text
IMX500 on Pi Zero W
    |  UDP JPEG chunks to this PC :8765
This PC  127.0.0.1:8770 browser
    |  AprilTag 36h11 id 0 on the newest complete frame
    |  TCP ASCII to ESP32 :8771
ESP32-WROOM-32   project name odin2 (hotspot)
    |  CRSF 420000 TX only
SpeedyBee F405 Mini   UART1   ANGLE mode
```

The Pi captures a center square, default 640×640, and sends UDP JPEG chunks to `ODIN_DESKTOP_HOST` port 8765. It does not detect and it does not speak UART. `ODIN_FRAME_SIZE` may be 640 or 960. `ODIN_JPEG_QUALITY` default 60. `ODIN_CAMERA_FPS` default 30. If `ODIN_DESKTOP_HOST` is unset, the Pi process exits.

This PC runs AprilTag 36h11 id 0 and the page on `127.0.0.1:8770`. The page asks for the ESP32 host, not the Pi host. Desktop listens for video on UDP 8765.

The ESP32 joins the hotspot and listens on TCP 8771. Copy `esp32/main/wifi_secrets.example.h` to `esp32/main/wifi_secrets.h` on the build machine. That file is gitignored.

500 ms of command-link silence still disarms. A dropped video frame clears the target and does not disarm.

The Pi does not draw a GUI. The desktop does not compute stick microseconds; it detects the tag and sends pilot lines. The ESP32 owns chase math, slew, CRSF, and the VL53 altitude reading.

## Wiring

| Function | Connection |
|---|---|
| Pi GPIO14 TX | ESP32 GPIO16 RX, UART1 |
| ESP32 GPIO17 TX | Pi GPIO15 RX, UART1 |
| Common ground | Pi GND to ESP32 GND |
| CRSF TX | ESP32 GPIO27 to FC UART1 RX, 420000 |
| I2C | ESP32 GPIO21 SDA, GPIO22 SCL, 400 kHz |
| VL53L5CX XSHUT | ESP32 GPIO25 |
| VL53L1X left XSHUT | ESP32 GPIO26, held low |
| VL53L1X right XSHUT | ESP32 GPIO33, held low |
| GPIO32, GPIO34, GPIO35 | Unused |

Do not wire PMW3901 or TF-Luna to the FC. L1X sensors stay in reset. UP-T1 may stay on FC UART2 but this firmware does not use it. FC UART4 BLE is not touched.

CRSF channels, clamped 1000–2000 µs:

| Index | Channel | Armed | Disarmed |
|---|---|---|---|
| 0 | Roll | bias + addition | bias |
| 1 | Pitch | bias + addition | bias |
| 2 | Throttle | mode thrust | 1000, immediate |
| 3 | Yaw | bias + addition | bias |
| 4 | AUX1 ARM | 2000 | 1000, immediate |
| 5 | AUX2 POSHOLD | 1000 always | 1000 |
| 6 | AUX3 ANGLE | 2000 | 1000, immediate |
| 7 | AUX4 | 1500 | 1500 |

Signs: roll+ right, pitch+ forward, yaw+ right.

## Modes and keys

Arming is not its own mode. H arms and enters hover. 1, 2, and L do nothing while disarmed. Esc disarms from any mode, including when a number field is focused. H, 1, 2, and L do not fire while a number input is focused.

| Key | Mode | Effect |
|---|---|---|
| H | HOVER | Arm. Roll, pitch, yaw on bias. Thrust slews to hover thrust |
| 1 | FOLLOW | Chase the AprilTag. Wire string is `FOLLOW` |
| 2 | HOLD | Position hold from the tag, not optical flow |
| L | LAND | Bias attitude. Thrust slews to land thrust. Stays armed |
| Esc | DISARMED | Throttle 1000, AUX1 and AUX3 low, same tick |

Failsafe: after the first byte on the desktop-to-ESP32 TCP link, 500 ms without another received byte disarms on the ESP32. The desktop posts `/heartbeat` every 200 ms while connected; if the browser has been silent for 1000 ms, the desktop sends `CMD DISARM` once and stops `PING`. GET `/state` does not count as a heartbeat. A dropped video frame sends a miss `PILOT` line and does not disarm.

## Chase and hold

Frame is a center square, default 640×640 (`ODIN_FRAME_SIZE` 640 or 960). Tag is AprilTag 36h11, id 0 only, detected on this PC. Area is the shoelace of the four corners, integer pixels squared.

```text
nx = (cx - w/2) / (w/2)    right positive
ny = (cy - h/2) / (h/2)    down positive
```

FOLLOW, tag seen and younger than 300 ms:

- yaw addition = nx * yaw_max
- roll addition = nx * roll_max
- pitch addition = pitch_max + (pitch_min - pitch_max) * abs(nx)
- thrust addition = -ny * thrust_target
- thrust base = hover thrust, not bias thrust

Tag miss or tag older than 300 ms: stay in the current mode, additions are 0. Roll, pitch, yaw, and the follow thrust addition slew back. The hold area reference is not cleared by a miss.

HOLD: same yaw and roll law. On entry, clear the saved area and wait 1500 ms. Until then pitch addition is 0. Then save the next non-zero area R. `delta = clamp(area/R - 1, -1, 1)`, pitch addition = -delta * pitch_max. Bigger tag pitches back. Thrust stays on hover thrust. Re-entering HOLD resamples R.

Action thrust, in the Hover section of the GUI: one flat extra, not an increment. While FOLLOW or HOLD is commanding a non-zero pitch or roll addition, add `action_thrust_us` once on top of the thrust target. Yaw-only adds nothing. Hover, land, disarm, and a tag miss add nothing. The extra uses `action_slew_us_s` only. Example: hover 1560 and action 20 is 1580 while pitching, then 1560 again when the tilt command returns to 0. Default action thrust is 0 so older behavior stays until the field is set. During FOLLOW, a visible tag with pitch_max above 0 is always a forward pitch, even when the tag is centered, so the extra stays on for that whole follow.

Slew is microseconds per second with a fractional remainder, divided by `CRSF_TASK_HZ` (100), not a hardcoded 100 in a way that would drift if that rate changes.

## Command link

ASCII, one line, newline terminated. Desktop to ESP32 over TCP 8771:

```text
BIAS roll pitch yaw thrust
CHASE yaw_max roll_max pitch_min pitch_max thr_target yaw_slew roll_slew pitch_slew thr_slew
HTHR hover_thrust hover_slew land_thrust land_slew action_thrust action_slew
SAFE area_stop deadband_pct lpf_ms agl_ceiling_mm
CMD HOVER
CMD DISARM
PILOT FOLLOW cx cy area w h
PILOT HOLD cx cy area w h
PILOT HOVER 0 0 0 w h
PILOT LAND 0 0 0 w h
PILOT DISARM 0 0 0 w h
PING
```

No tag: `PILOT <MODE> 0 0 0 <w> <h>`. `PILOT` is sent on every detect pass and immediately on a mode change. Only `CMD HOVER` arms.

ESP32 to desktop at 20 Hz:

```text
STATE mode arm roll pitch thr yaw agl_mm
PONG
```

`agl_mm` is -1 until the bottom-row center pair of the VL53L5CX 8×8 is read (zones 59 and 60). That reading is telemetry only. It does not fly the aircraft yet.

## Defaults

| Field | Default |
|---|---|
| bias roll, pitch, yaw, thrust | 1500, 1500, 1500, 1350 |
| yaw max / slew | 80 / 400 |
| roll max / slew | 30 / 200 |
| pitch min / max / slew | 0 / 120 / 300 |
| thrust target / slew | 40 / 250 |
| hover thrust / slew | 1350 / 2500 |
| land thrust / slew | 1100 / 2500 |
| action thrust / slew | 0 / 250 |

First-flight trims are UI values, not code defaults: pitch_max about 70, thrust_target 0, roll_max 0. Bias thrust is not the chase or hold throttle base.

## GUI

The GUI is only on the desktop. The Pi does not serve HTTP. Opening `http://<pi-ip>/` is connection refused. That is expected.

```powershell
cd desktop
python server.py
```

Open `http://127.0.0.1:8770/`. Type the ESP32 IPv4 address on the hotspot and press Connect. The video URL is `/stream` (local MJPEG from assembled UDP frames). The page adds a query string so the browser does not cache it. The server must ignore that query string. Status is `GET http://127.0.0.1:8770/state` or the JSON returned by `POST /heartbeat` while connected.

## Pi service

```bash
sudo systemctl status odin-pi.service
journalctl -u odin-pi.service -n 40 --no-pager
```

Code path on the Pi: `/home/odin-1/odin-2/pi`. Required env: `ODIN_DESKTOP_HOST` (this PC IPv4). Optional: `ODIN_FRAME_SIZE` (640 or 960, default 640), `ODIN_JPEG_QUALITY` (default 60), `ODIN_CAMERA_FPS` (default 30), `ODIN_VIDEO_PORT` (default 8765). Camera config is in `pi/odin_pi/camera_worker.py`: sensor 2028×1520 10-bit, main square YUV420 sized to `ODIN_FRAME_SIZE`, frame duration from `ODIN_CAMERA_FPS`, centered scaler crop on the 4056×3040 array. Y plane is the first side×side bytes. No IMX500 `.rpk` network is loaded.

To copy a newer `pi/` tree, shut the service down, copy the files, and start it again. A camera open takes about a minute on the Zero W before `Camera started` appears in the log.

## ESP32 build

Windows, ESP-IDF. Copy `esp32/main/wifi_secrets.example.h` to `esp32/main/wifi_secrets.h` and fill in the hotspot SSID and credentials there. Do not commit `wifi_secrets.h`. Do not flash unless asked. Name the COM port first. Props off.

```powershell
. "C:\Espressif\tools\Microsoft.v6.0.2.PowerShell_profile.ps1"
Set-Location esp32
idf.py build
idf.py -p COMx flash
```

`sdkconfig.defaults` selects size optimization. `esp32/build/` is not in git. `chase_test.c` is not linked into the IDF app. This PC has no host gcc, so that test has not been executed here. The IDF build completed after the action-thrust change.

## Safety

KILL is throttle minimum and arm low, immediate. Never enable a Betaflight autopilot on this aircraft. Never declare it flight-ready from a host build or from the Pi service being up.
