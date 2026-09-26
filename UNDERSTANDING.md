# Odin-2 — what we are building

Basic indoor chase test. Same airframe wiring as `full-autonomous` `docs/wiring.md`. No position hold. `full-autonomous` and `base-tracking` are read-only references.

Two things go on the aircraft. The desktop is only the screen and the keyboard.

- **Pi Zero 2 W** — camera, AprilTag, video back to the desktop, UART bridge to the ESP32
- **ESP32-WROOM-32** — chase math, CRSF sticks, VL53L5CX altitude reading
- **Desktop** — bias inputs, chase inputs, live video. Nothing else renders a GUI

## Keys

- **H** — arm and hover. Roll, pitch, and yaw stay on the bias. Thrust slews to the hover thrust preset at the hover slew. Default hover thrust is 1350, the same `hover_throttle` as `full-autonomous`, and the default slew is 2500 µs/s (25 µs per 100 Hz tick, that firmware’s `slew_thr_us`).
- **1** — chase mode. Fly at the AprilTag
- **L** — leave chase and slew thrust to the land thrust preset at the land slew (defaults 1100 µs and 2500 µs/s). Does not track
- **Escape** — disarm immediately. Throttle minimum, arm switch low. No slew

`1` and `L` do nothing while disarmed. `H` is the only arm key.

## What hover means

Hover is trimmed **angle mode**, not position hold.

- AUX1 (arm) high
- AUX2 (POSHOLD) stays low. Always
- AUX3 (ANGLE) high while armed
- Roll, pitch, yaw, and thrust sit on the bias numbers
- No optical flow. No altitude loop. No `pos_hold` code in this folder

Bias is the calibration. Every chase addition is stacked on top of it. Bias defaults match `full-autonomous` `pilot_state.c`: roll 1500, pitch 1500, yaw 1500, thrust 1350.

Stick signs match that firmware: roll+ is right, pitch+ is forward, yaw+ is right. Channels are roll, pitch, throttle, yaw, then AUX1–AUX4. CRSF at 420000 on ESP32 GPIO27 into FC UART1.

## Chase

The Pi reports the AprilTag center in pixels, plus the frame size. It does not compute sticks.

The ESP32 finds the center of the 320×320 frame and the error of that pixel.

- Tag on the right: yaw right, and a small roll right, together
- Tag nearer the horizontal center: more forward pitch
- Tag out at the side: less forward pitch
- Tag above center: thrust up. Tag below center: thrust down
- Each axis has its own slew, so the sticks ease onto the new value

Yaw and roll rest on the bias when the tag is centered. There is no second yaw minimum. The yaw preset is only how far yaw may move away from the bias, plus the slew. Roll is the same idea: one maximum roll addition, plus a slew.

Pitch has a minimum addition and a maximum addition. Both are added to bias pitch. Center of the view uses the maximum. The left or right edge uses the minimum.

Thrust has one target addition and a slew. Vertical error scales it. Centered vertically, thrust stays on the bias.

If the tag leaves the frame, or a detection pass misses it, chase mode stays on and every addition drops to zero, including pitch and thrust. The aircraft sits on the bias until a new hit arrives. No coasting on the last pixel.

## Landing

`L` keeps roll, pitch, and yaw on the bias and slews thrust to a land preset (default 1100). The rangefinder is not in this loop. The aircraft stays armed until Escape.

## Camera

- IMX500 on the Pi CSI port, used as a normal camera. AprilTag runs on the CPU, not on the IMX500 neural block
- Center-square crop, scaled to **320×320**
- Grayscale from the Y plane of YUV420, so detection does not convert RGB
- Video path targets 30 fps or better and does not wait on detection
- Detection is asynchronous and always consumes the newest frame. Skipped frames are expected
- Family **36h11**, id **0** (the printed tag from `base-tracking`)
- The stream back to the desktop is that same view with a box only while the latest detect pass still sees the tag

## Who talks to whom

```text
Desktop  -- Wi-Fi: presets + H / 1 / L / Escape -->  Pi Zero 2 W
Desktop  <-- Wi-Fi: 320×320 video + box + state --  Pi Zero 2 W
Pi       -- UART 115200 ASCII ------------------>  ESP32
ESP32    -- CRSF -------------------------------->  FC UART1
ESP32    -- I2C --------------------------------->  VL53L5CX (altitude reading only)
```

The desktop never talks to the ESP32. The Pi never computes sticks.

## Rangefinder, copied for later

Same I2C pins as the reference: SDA 21, SCL 22, XSHUT 25 for the VL53L5CX. The left and right VL53L1X stay wired (XSHUT 26 and 33) and are held in reset so they do not sit on the bus. Their ranges are not read.

Altitude is the average of the **bottom-row center pair** of the 8×8 (driver zones 59 and 60). It is reported in status only. Hover, chase, and land do not use it.

Optical flow is not read and has no code here. TF-Luna and PMW3901 are not copied. GPIO32, GPIO34, and GPIO35 stay unused. UP-T1 can remain on FC UART2; this firmware does not use it and does not turn on POSHOLD. FC UART4 (BLE) is not touched.

## Failsafe

- Pi UART silent for 500 ms → same as Escape
- Desktop silent to the Pi for 500 ms → Pi sends disarm

## What we are not building

- Position hold, altitude hold, flow hold, GOTO, scan, intercept
- A GUI on the Pi
- YOLO
- Any edit under `full-autonomous` or `base-tracking`

## Locked assumptions

Correct these if any are wrong. The build uses them as written.

- `H` is arm + hover. There is no separate arm key
- `L` does not disarm
- AprilTag is 36h11 id 0
- Angle mode, not POSHOLD, so pitch and roll are attitude tilts
- Land thrust default is 1100 µs until you type another number
- Bottom-row zones 59 and 60. If the module is rotated on the bench, only those two indices change
- The desktop has a field for the Pi’s address. No address is hardcoded
