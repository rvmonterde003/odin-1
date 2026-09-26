# Odin-2

Indoor AprilTag chase test for the KD aircraft. Desktop sends keys and presets. The Pi finds the tag. The ESP32 turns that into CRSF sticks. This folder is the whole flight stack for that test.

`SPEC.md` is the numeric contract. `UNDERSTANDING.md` is the original brief. This file is the handoff for another machine. Where they disagree, the code and the notes below are the later truth. A few older sentences in `SPEC.md` still say `CMD` or `STATE CHASE`; the wire format is `PILOT` and the mode string is `FOLLOW`.

Do not modify the sibling repos `full-autonomous` or `base-tracking`. Do not copy optical-flow `pos_hold` into this tree. Props stay off until a bench failsafe check. Do not flash the ESP32 until asked. Betaflight stays in ANGLE. AUX2 POSHOLD stays low. Failsafe stage 2 on the FC should be Drop. CRSF from the ESP32 is TX-only, so the FC will not see a radio failsafe by itself.

## What is running now

The flight computer in the airframe is a **Raspberry Pi Zero W** (Nanya DRAM on the board), not a Pi Zero 2 W. It is 32-bit only (`armv6l`). Raspberry Pi OS Lite 32-bit (Debian Trixie) is the image that boots. The 64-bit Lite image does not boot this board (green LED flashes 7 times: kernel not found).

The camera is the official **Raspberry Pi AI Camera, Sony IMX500**. It is used as a normal camera. AprilTag runs on the Pi CPU with OpenCV ArUco, not on the IMX500 neural processor.

As of 2026-09-25 on the bench PC:

- Pi hostname `odin-1`, user `odin-1`, password `odin-1`.
- It joins this PC's hotspot SSID `VINCENTzypher`. The hotspot must stay **WPA2 only**. The Zero W cannot join WPA3.
- Last address was `192.168.137.7`. DHCP can change it. The name is `odin-1.local`. Prefer the IPv4 address. Windows often resolves the name to IPv6 link-local first, and that path does not reach the Pi.
- SSH is on. Wi-Fi power save is off (`wifi.powersave = 2` and `iw dev wlan0 set power_save off`).
- UART for the ESP32 is on and the serial login console is removed. `/dev/serial0` is `ttyAMA0`. `enable_uart=1` and `dtoverlay=disable-bt` are in `/boot/firmware/config.txt`. Bluetooth is disabled so the GPIO14/15 UART baud stays stable.
- Camera auto-detect does not see the IMX500 on this Zero W. `/boot/firmware/config.txt` has `camera_auto_detect` commented out and `dtoverlay=imx500` set. After that, `rpicam-hello --list-cameras` shows `imx500 [4056x3040]`. The camera RP2040 firmware was already version 15. Do not reflash that firmware.
- Packages on the Pi: `imx500-all`, `imx500-firmware`, `python3-opencv`, `python3-picamera2`, `python3-serial`, `iw`. Code lives at `/home/odin-1/odin-2/pi`. systemd unit `odin-pi.service` is enabled.
- The camera loop on this Zero W runs at about **2 fps**, not 30. The sensor is configured for 30 fps. The 2 fps number is the capture loop itself. The desktop stream shows those same frames. Detection reads them too.
- The ESP32 firmware has been built (`idf.py build` completed) and **has not been flashed**. Plug the ESP32 in only when asked, props off.

## Nodes

```text
Desktop browser  127.0.0.1:8770
    |  Wi-Fi HTTP
Pi Zero W        :8766   camera, AprilTag, UART
    |  UART 115200 8N1 ASCII
ESP32-WROOM-32   project name odin2
    |  CRSF 420000 TX only
SpeedyBee F405 Mini   UART1   ANGLE mode
```

The Pi does not draw a GUI and does not compute stick microseconds. The desktop does not compute sticks either. It only sends presets and key commands. The ESP32 owns chase math, slew, CRSF, and the VL53 altitude reading.

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

Failsafe: after the first Pi byte, 500 ms of UART silence disarms. After the first desktop POST, 500 ms without a POST makes the Pi send `PILOT DISARM 0 0 0`. The desktop posts `/heartbeat` every 200 ms while connected. GET `/state` does not count.

## Chase and hold

Frame is 320×320. Tag is AprilTag 36h11, id 0 only. Area is the shoelace of the four corners, integer pixels squared.

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

## UART lines

ASCII, one line, newline terminated. Pi to ESP32:

```text
BIAS roll pitch yaw thrust
CHASE yaw_max roll_max pitch_min pitch_max thr_target yaw_slew roll_slew pitch_slew thr_slew
HTHR hover_thrust hover_slew land_thrust land_slew action_thrust action_slew
PILOT FOLLOW cx cy area
PILOT HOLD cx cy area
PILOT HOVER 0 0 0
PILOT LAND 0 0 0
PILOT DISARM 0 0 0
PING
```

No tag: `PILOT <MODE> 0 0 0`. `PILOT` is sent on every detect pass and immediately on a mode change.

ESP32 to Pi at 20 Hz:

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

The GUI is only on the desktop. The Pi does not serve a page on port 80. Opening `http://<pi-ip>/` is connection refused. That is expected.

```powershell
cd desktop
python server.py
```

Open `http://127.0.0.1:8770/`. Type the Pi IPv4 address and press Connect. The video URL is `/stream`. The page adds a query string so the browser does not cache it. The server must ignore that query string. A direct status check is `http://<pi-ip>:8766/state`.

## Pi service

```bash
sudo systemctl status odin-pi.service
journalctl -u odin-pi.service -n 40 --no-pager
```

Code path on the Pi: `/home/odin-1/odin-2/pi`. UART device: `/dev/serial0`, override with `ODIN_UART`. Camera config is in `pi/odin_pi/camera_worker.py`: sensor 2028×1520 10-bit, main 320×320 YUV420, frame duration 33333 µs, centered scaler crop. Y plane is the first 320×320 bytes. No IMX500 `.rpk` network is loaded.

To copy a newer `pi/` tree, shut the service down, copy the files, and start it again. A camera open takes about a minute on the Zero W before `Camera started` appears in the log.

## ESP32 build

Windows, ESP-IDF. Do not flash unless asked. Name the COM port first. Props off.

```powershell
. "C:\Espressif\tools\Microsoft.v6.0.2.PowerShell_profile.ps1"
Set-Location esp32
idf.py build
idf.py -p COMx flash
```

`sdkconfig.defaults` selects size optimization. `esp32/build/` is not in git. `chase_test.c` is not linked into the IDF app. This PC has no host gcc, so that test has not been executed here. The IDF build completed after the action-thrust change.

## Safety

KILL is throttle minimum and arm low, immediate. Never enable a Betaflight autopilot on this aircraft. Never declare it flight-ready from a host build or from the Pi service being up.
