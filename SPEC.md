# Odin-2 SPEC

Simpler than `full-autonomous`. Wiring is that repo’s `docs/wiring.md`. Behavior is a four-key chase test. No position hold.

Do not modify `full-autonomous` or `base-tracking`. Do not flash. Do not open a serial port. Props stay off.

## Nodes

| Node | Role |
|------|------|
| Desktop `desktop/` | Browser UI on 127.0.0.1. Proxies the Pi. Keyboard and number fields only |
| Pi `pi/` | 320×320 gray camera, async AprilTag, MJPEG, UART bridge |
| ESP32 `esp32/` | Parse UART, slew sticks, CRSF, VL53L5CX altitude telemetry |

## Wiring (do not redesign)

| Function | Pin |
|----------|-----|
| Pi GPIO14 TX → ESP32 RX | GPIO16, UART1, 115200 8N1 |
| ESP32 TX → Pi GPIO15 RX | GPIO17, UART1, 115200 8N1 |
| CRSF TX → FC UART1 RX | GPIO27, UART2, 420000 |
| I2C SDA / SCL | GPIO21 / GPIO22, 400 kHz |
| XSHUT VL53L5CX | GPIO25, driven for bring-up |
| XSHUT VL53L1X left | GPIO26, held low |
| XSHUT VL53L1X right | GPIO33, held low |
| GPIO32, GPIO34, GPIO35 | Unused. No TF-Luna, no PMW3901 |

CRSF channels, 1000–2000 µs:

| Index | Channel | Armed hover | Disarmed |
|-------|---------|-------------|----------|
| 0 | Roll | bias roll | bias roll |
| 1 | Pitch | bias pitch | bias pitch |
| 2 | Throttle | bias thrust | 1000 |
| 3 | Yaw | bias yaw | bias yaw |
| 4 | AUX1 ARM | 2000 | 1000 |
| 5 | AUX2 POSHOLD | 1000 | 1000 |
| 6 | AUX3 ANGLE | 2000 | 1000 |
| 7 | AUX4 | 1500 | 1500 |

Signs: roll+ right, pitch+ forward, yaw+ right. Clamp every channel to 1000–2000.

## Modes

`DISARMED` is the boot mode.

| Key | Mode | Effect |
|-----|------|--------|
| H | `HOVER` | Arm. Roll, pitch, and yaw stay on bias. Thrust slews to `hover_thrust_us` at `hover_slew_us_s` |
| 1 | `FOLLOW` | Ignored if disarmed. Existing chase law: yaw and roll from left/right, pitch from how centered the tag is, thrust from up/down |
| 2 | `HOLD` | Ignored if disarmed. Yaw and roll from left/right, same gains as follow. Pitch from tag area versus the size sampled 1.5 s after hold starts. Thrust stays on `hover_thrust_us` |
| L | `LAND` | Ignored if disarmed. Roll, pitch, and yaw stay on bias. Thrust slews to `land_thrust_us` at `land_slew_us_s` |
| Escape | `DISARMED` | Immediate. Throttle 1000, AUX1 1000, AUX3 1000. Slew does not apply |

Tag miss inside `CHASE`: mode stays `CHASE`. Desired additions become 0. Slew returns the sticks to bias, including pitch and thrust.

Pi UART with no byte for 500 ms → `DISARMED` immediate, same outputs as Escape.

Desktop with no POST for 500 ms → Pi sends `CMD DISARM`.

## Presets

Absolute bias, microseconds:

| Field | Default |
|-------|---------|
| `bias_roll_us` | 1500 |
| `bias_pitch_us` | 1500 |
| `bias_yaw_us` | 1500 |
| `bias_thrust_us` | 1350 |

Chase additions, microseconds, applied on top of bias:

| Field | Default | Meaning |
|-------|---------|---------|
| `yaw_max_us` | 80 | Full-scale yaw addition at the left or right edge |
| `yaw_slew_us_s` | 400 | Yaw slew, microseconds per second |
| `roll_max_us` | 30 | Full-scale roll addition, same sign as yaw |
| `roll_slew_us_s` | 200 | Roll slew |
| `pitch_min_us` | 0 | Pitch addition at a horizontal edge |
| `pitch_max_us` | 120 | Pitch addition at horizontal center |
| `pitch_slew_us_s` | 300 | Pitch slew |
| `thrust_target_us` | 40 | Full-scale thrust addition at the top or bottom edge |
| `thrust_slew_us_s` | 250 | Chase thrust slew only |

Hover and land, microseconds. These match `full-autonomous` `pilot_state.c`: hover throttle 1350, throttle slew 25 µs per 100 Hz tick (2500 µs/s).

| Field | Default | Meaning |
|-------|---------|---------|
| `hover_thrust_us` | 1350 | Exact throttle target while `HOVER` |
| `hover_slew_us_s` | 2500 | Thrust slew while `HOVER` |
| `land_thrust_us` | 1100 | Exact throttle target while `LAND` |
| `land_slew_us_s` | 2500 | Thrust slew while `LAND` |
| `action_thrust_us` | 0 | Flat extra thrust while follow or hold is pitching or rolling. Added once, not each tick. Yaw-only, hover, and land stay at the base thrust |
| `action_slew_us_s` | 250 | Slew of that extra only. The base thrust keeps hover, land, or follow thrust slew |

## Chase math

Frame width `w` and height `h` come from the Pi (320 and 320). Tag center `(cx, cy)` only when `seen=1`.

```text
nx = (cx - w/2) / (w/2)     right positive, clamp -1..1
ny = (cy - h/2) / (h/2)     down positive, clamp -1..1
ax = abs(nx)

yaw_add   = nx * yaw_max_us
roll_add  = nx * roll_max_us
pitch_add = pitch_max_us + (pitch_min_us - pitch_max_us) * ax
thr_add   = -ny * thrust_target_us
```

Desired sticks:

```text
roll  = bias_roll  + roll_add
pitch = bias_pitch + pitch_add
yaw   = bias_yaw   + yaw_add
thr   = bias_thrust + thr_add
```

`seen=0`, or a `TAG` older than 300 ms, forces every chase addition to 0. Chase thrust is `hover_thrust_us` plus the vertical addition, and it uses `thrust_slew_us_s`. `bias_thrust_us` is not the chase throttle base. `HOVER` does not use bias thrust: desired thrust is `hover_thrust_us` and the thrust slew is `hover_slew_us_s`. `LAND` sets thrust desired to `land_thrust_us` and uses `land_slew_us_s`. Roll, pitch, and yaw stay on their own slews in every armed mode.

Slew runs at the 100 Hz CRSF tick for every axis except on the disarm edge. Carry a fractional-microsecond remainder so a slew of 250 µs/s moves 2 µs on some ticks and 3 µs on others. Slew 0 snaps to the target. Disarm snaps throttle to 1000 and AUX1/AUX3 low on that same tick.

Worked CHASE examples with defaults, bias 1500/1500/1500/1350, `seen=1`, `w=h=320`. These are desired values before slew:

| cx, cy | roll | pitch | yaw | thr |
|--------|------|-------|-----|-----|
| 160, 160 | 1500 | 1620 | 1500 | 1350 |
| 320, 160 | 1530 | 1500 | 1580 | 1350 |
| 0, 160 | 1470 | 1500 | 1420 | 1350 |
| 160, 0 | 1500 | 1620 | 1500 | 1390 |
| 160, 320 | 1500 | 1620 | 1500 | 1310 |
| seen=0 | 1500 | 1500 | 1500 | 1350 |

## Position hold

No optical flow. Hold uses the same AprilTag, id 0, and the same chase gains and slews.

The Pi sends one line that carries the three values: mode, target position, target size.

```text
PILOT HOLD 212 142 1840
PILOT FOLLOW 212 142 1840
PILOT HOVER 0 0 0
PILOT LAND 0 0 0
PILOT DISARM 0 0 0
```

Field order: `mode cx cy area`. `cx cy` is the tag center in the 320×320 frame. `area` is the quadrilateral area of the four tag corners in pixels, rounded to an integer. No tag: `cx cy area` are 0. Send this line on every completed detect pass and again immediately when the desktop changes mode.

`area` bigger than the saved size means the tag is closer, so pitch goes backward. Smaller means farther, so pitch goes forward. Pitch forward is the same sign as follow (`pitch+`).

On the edge into `HOLD`, clear the saved area and start a 1500 ms timer. Until that timer elapses, yaw and roll still track left and right, and pitch addition stays 0. At 1500 ms, save the next non-zero area. Leaving hold and entering again takes a new sample. A miss or a tag older than 300 ms zeros yaw, roll, and pitch additions and does not change the saved area.

Full-scale pitch is `pitch_max_us`. With saved area `R` and current area `A`:

```text
delta = clamp(A / R - 1, -1, 1)
pitch_add = -delta * pitch_max_us
```

`A = 2R` pitches back by `pitch_max_us`. `A = R` adds nothing. `A = 0.5R` pitches forward by half of `pitch_max_us`. Yaw and roll use the follow formulas and `yaw_max_us`, `roll_max_us`, and their slews. Thrust desired is `hover_thrust_us` with `hover_slew_us_s`. `pitch_min_us` and `thrust_target_us` stay follow-only.

Worked HOLD examples, bias pitch 1500, `pitch_max_us` 120, reference area 1000, tag centered so yaw and roll adds are 0. Desired values before slew:

| When | area | pitch |
|------|------|-------|
| 1.0 s after entering hold | 2000 | 1500 |
| after the sample, area matches | 1000 | 1500 |
| tag larger | 2000 | 1380 |
| tag half size | 500 | 1560 |
| tag missing | 0 | 1500 |

## UART lines

ASCII, one line, `\n` terminated, integers only. Pi → ESP32:

```text
BIAS 1500 1500 1500 1350
CHASE 80 30 0 120 40 400 200 300 250
HTHR 1350 2500 1100 2500 0 250
CMD HOVER
CMD CHASE
CMD LAND
CMD DISARM
TAG 1 160 140 320 320
TAG 0 0 0 320 320
PING
```

`CHASE` field order: `yaw_max roll_max pitch_min pitch_max thr_target yaw_slew roll_slew pitch_slew thr_slew`.

`HTHR` field order: `hover_thrust hover_slew land_thrust land_slew action_thrust action_slew`.

Action thrust: while `FOLLOW` or `HOLD`, if `roll_add` or `pitch_add` is non-zero, add `action_thrust_us` once on top of the thrust target. Yaw-only (`roll_add` and `pitch_add` both 0) adds nothing. Hover, land, disarm, and a tag miss add nothing. Example: hover 1560 and action 20 while pitching forward is 1580, then 1560 again when the tilt command returns to 0. The extra uses `action_slew_us_s` and does not stack on itself.

ESP32 → Pi at 20 Hz:

```text
STATE HOVER 1 1500 1500 1350 1500 -1
PONG
```

`STATE` field order: `mode arm roll pitch thr yaw agl_mm`. `agl_mm` is -1 until the sensor returns a range. Mode strings: `DISARMED` `HOVER` `CHASE` `LAND`.

Unknown lines are ignored. A partial line never changes sticks.

## Pi camera

- picamera2 `create_video_configuration`. Pin the IMX500 readout to **2028×1520, 10-bit** (`sensor={"output_size": (2028, 1520), "bit_depth": 10}`). Do not use the 4056×3040 mode (about 10 fps). Do not load an IMX500 `.rpk` network. AprilTag stays on CPU `cv2.aruco`.
- `main={"size": (320, 320), "format": "YUV420"}`. Fixed 30 fps with `FrameDurationLimits` `(33333, 33333)`.
- After `configure()`, set `ScalerCrop` to a centered square in **4056×3040 pixel-array** coordinates, then `start()`.
- Buffer format YUV420. The Y plane is the first `320*320` bytes. Detection and the streamed picture use that plane only.
- Camera loop does not call the detector. Target 30 fps. If the ISP cannot hold 30, run at the highest rate it does hold and log that rate. Do not drop the camera loop to the detector rate
- One detect thread. It overwrites a single “latest frame” slot. It never processes a stale queued frame
- `cv2.aruco` dictionary `DICT_APRILTAG_36h11`. Accept id 0 only
- On each completed pass, send one `TAG` line. A miss is `TAG 0 ...` immediately. Do not repeat the previous hit
- Draw the box on the MJPEG frame only when that frame’s matching pass found id 0. A miss clears the box
- Four threads: camera, detect, UART, HTTP. Pi Zero 2 W has four Cortex-A53 cores. Do not pin AprilTag to the camera thread

## Safety and smoothing (added 25 Sep 2026)

Motivation: the board on the aircraft is now an original Pi Zero W, detection runs at 15 Hz, and end-to-end vision latency is about 160 ms. A plain proportional law on pixel error hunts around the tag, and FOLLOW had no distance term, so nothing slowed the aircraft before it reached the tag.

New UART line, Pi → ESP32, sent with every preset:

```text
SAFE 0 10 150 0
```

Field order: `area_stop_px2 deadband_pct lpf_ms agl_ceiling_mm`. A value of 0 disables `area_stop_px2`, `lpf_ms` and `agl_ceiling_mm`.

| Field | Default | Meaning |
|-------|---------|---------|
| `area_stop_px2` | 0 (off) | FOLLOW standoff. Pitch addition is scaled by `clamp(1 - area / area_stop, -0.5, 1)`: full forward when far, zero at the stop area, up to half `pitch_max_us` backward when closer. Calibrate by holding the tag at the wanted distance and reading `area` off the stream |
| `deadband_pct` | 10 | Percent of the half-frame around centre where the yaw, roll and thrust additions are 0. Rescaled so the frame edge is still full scale. Pitch fade uses the raw offset |
| `lpf_ms` | 150 | First-order low-pass on the FOLLOW and HOLD targets, before the slew, at the 100 Hz tick. Seeds on the first tick of a camera mode. Hover, land and disarm bypass it |
| `agl_ceiling_mm` | 0 (off) | When `agl_mm` is valid and at or above this, throttle is capped at `hover_thrust_us`. Applied after the stick law in `main.c`. It only ever removes thrust |

Hard firmware limits, not adjustable from any preset, applied after slew and action thrust on every tick: roll and pitch 1350–1650, yaw 1380–1620, throttle never above 1650. Disarm outputs are unchanged and still win.

Action thrust is an addition in microseconds and is capped at 200. The earlier code passed it through the 1000–2000 stick clamp, which turned 20 into a target of 1000 and made the throttle climb 20 µs every tick.

Recommended first-flight preset on the Zero W: `yaw_max_us` 40, `roll_max_us` 0, `pitch_max_us` 60, `thrust_target_us` 20, `hover_slew_us_s` 800, deadband 10, filter 150, standoff calibrated before the first FOLLOW.

The host chase test also covers the deadband, the standoff, the hard limits, the filter and the ceiling.

## Arming, watchdog and desktop traffic (revised 25 Sep 2026 after a bench flyaway)

- The Pi boots in `DISARM` and its first UART line is `PILOT DISARM 0 0 0`. It never boots in HOVER. A previous build defaulted to HOVER, which armed the FC on every service start because each detect pass repeats `PILOT <mode>`.
- The ESP32 arms only on `CMD HOVER`. A `PILOT HOVER` line never moves the mode out of DISARMED; it only keeps HOVER once armed. The desktop H key makes the Pi send `CMD HOVER` followed by the PILOT line.
- Desktop-silence watchdog on the Pi is 1000 ms, not 500. Heartbeat round trips on the Zero W over the hotspot are about 30 ms median, 80 ms p90 at 15 fps, but 500 ms tripped on ordinary jitter at 20 fps. The ESP32's 500 ms Pi-silence failsafe is unchanged and is the hard stop.
- Desktop polling is one `POST /heartbeat` every 200 ms which returns the state JSON, over a persistent HTTP/1.1 connection to the Pi's IPv4 address, with TCP_NODELAY on both servers. The earlier 100 ms `/state` plus 200 ms heartbeat over fresh connections was 15 connections a second and cost more Pi CPU than the camera.
- Stream-only knobs on the Pi: `ODIN_STREAM_QUALITY` (JPEG quality, default 80) and `ODIN_STREAM_SCALE` (2 = 160x160 stream). Detection never sees the stream. `ODIN_CAMERA_FPS` default 15. 20 fps saturates the Zero W and breaks heartbeat latency.
- The detect thread always reports a finished pass. It never discards a result because the camera published during the pass.

Props off, or battery out, for every service restart, deploy, flash and FC plug-in.

## Desktop UI

One page:

- Pi host field, default empty, plus a connect control
- Bias: roll, pitch, yaw, thrust
- Hover: hover thrust, hover slew, land thrust, land slew
- Chase: yaw max, yaw slew, roll max, roll slew, pitch min, pitch max, pitch slew, thrust target, thrust slew
- Live MJPEG
- Text line: mode, arm, agl_mm, tag seen, cx, cy

Changing a number POSTs the full preset. Keys POST a command. Escape disarms even when a number field is focused. `H`, `1`, and `L` do not fire while a number field is focused.

## Altitude

Copy the VL53L5CX driver into `esp32/`. Bring up the 8×8 only. Hold both L1X XSHUT pins low before I2C traffic. Average distance of zones **59** and **60** (bottom row, columns 3 and 4). If one zone is invalid, use the other. If both are invalid, `agl_mm = -1`. Do not feed `agl_mm` into the stick law.

## Tasks

| Task | Core | Priority | Stack | Rate |
|------|------|----------|-------|------|
| `pi_uart` | 0 | 5 | 6144 | events, telemetry 20 Hz |
| `sensors` | 0 | 6 | 8192 | 15 Hz is enough for the 8×8 |
| `crsf_pilot` | 1 | 8 | 4096 | 100 Hz stick slew + CRSF |

No `pos_hold.c`. No flow fields. No TF-Luna. No PMW3901.

## Definition of done

1. Host chase test prints `chase ok` and exits 0. Cases are the table above, plus LAND desired thrust 1100 with roll/pitch/yaw at bias, plus disarm thrust 1000 with arm channel 1000.
2. `idf.py build` prints `Project build complete`. Binary is not flashed.
3. `python -m pytest -q` in `pi/` passes the latest-frame and TAG-line tests without a camera.
4. `python -m pytest -q` in `desktop/` passes the proxy route tests without a Pi.
5. Repo search of `odin-2` finds no `pos_hold`, no `pmw3901`, no `tfluna`.

## File ownership

| Owner | May write | Must not write |
|-------|-----------|----------------|
| Desktop builder | `desktop/**` | `pi/**`, `esp32/**`, this SPEC, `UNDERSTANDING.md` |
| Pi builder | `pi/**` | `desktop/**`, `esp32/**`, this SPEC, `UNDERSTANDING.md` |
| ESP32 builder | `esp32/**` | `pi/**`, `desktop/**`, this SPEC, `UNDERSTANDING.md`, anything outside `odin-2` |
