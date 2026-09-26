# Desktop AprilTag stream

Date: 2026-09-26

This branch moves AprilTag off the Pi Zero W and sends pilot commands from this PC straight to the ESP32. `main` stays the current stack, where the Pi detects the tag and talks to the ESP32 over UART.

The printed tag is unchanged: AprilTag 36h11, id 0. A later branch will replace that detector with a YOLO-class model on the 5090. This branch does not use the GPU. AprilTag runs on this PC's CPU.

## Goal

The Pi only captures and streams. This PC detects the tag on the newest complete frame and sends the target, the presets, and the pilot keys to the ESP32 over the hotspot. The ESP32 still owns chase math, slew, CRSF, and the VL53 reading.

Success on the bench, props off, nothing flashed until asked:

- The Pi holds 30 fps at 640×640 with no frame queue.
- This PC draws a box only for a tag found in a complete frame.
- The ESP32 disarms when the command TCP connection is silent for 500 ms.
- A dropped video frame does not disarm and does not coast the last pixel.

## Architecture

```text
IMX500 on Pi Zero W
    |  UDP JPEG chunks, latest frame only
This PC  127.0.0.1:8770 browser
    |  AprilTag 36h11 id 0 on the newest complete frame
    |  TCP ASCII, one client
ESP32 on the hotspot
    |  CRSF 420000
Flight controller, ANGLE, AUX2 held low
```

The Pi does not open the UART to the ESP32 and does not serve HTTP. The browser does not talk to the Pi. The desktop process binds the video port and opens TCP to the ESP32.

Hotspot SSID and password are not stored in git. The Pi gets them from the OS image. The ESP32 gets them from a local header, described below.

## Pi

One process. Capture, encode, send.

The sensor mode stays `2028×1520` at 10-bit, with the existing center-square scaler crop of the 4056×3040 array. The stream size is that square scaled to the main buffer.

| Environment | Default | Rule |
|---|---|---|
| `ODIN_FRAME_SIZE` | `640` | Square side in pixels. Allowed values: 640 and 960. Anything else: log the value and exit. No silent fallback. |
| `ODIN_CAMERA_FPS` | `30` | Frame duration is `1_000_000 / fps` microseconds, both limits set to that value. |
| `ODIN_JPEG_QUALITY` | `60` | JPEG quality 1–100. |
| `ODIN_DESKTOP_HOST` | unset | IPv4 of this PC on the hotspot. If unset, log and exit. |
| `ODIN_VIDEO_PORT` | `8765` | UDP destination port. |

The capture loop publishes one buffer. The sender takes that buffer, encodes it, and transmits it. If a newer capture arrives during encode or send, the sender finishes the frame it already started, then encodes the newest buffer and drops the ones in between. It does not grow a queue.

JPEG bytes are split into chunks. Each datagram is one chunk. The Pi does not retransmit and does not wait for an ack.

### UDP chunk

Wire header, 16 bytes, little-endian, then payload. The payload length is the datagram length minus 16. There is no length field.

| Offset | Type | Meaning |
|---|---|---|
| 0 | 4 bytes | Magic bytes `4F 4A 50 47` (`OJPG`) |
| 4 | uint32 | `frame_id`, increases by 1 for each captured frame, wraps naturally |
| 8 | uint16 | `chunk_index`, starting at 0 |
| 10 | uint16 | `chunk_count`, at least 1 |
| 12 | uint16 | width |
| 14 | uint16 | height |
| 16 | bytes | JPEG payload, 1400 bytes except the last chunk |

A full chunk is 1416 bytes, under the 1472-byte UDP payload that fits in one 1500-byte Ethernet frame. The chunk size stays 1400 so the hotspot does not fragment it. A datagram with the wrong magic, a header shorter than 16 bytes, `chunk_count` of 0, or `chunk_index` outside `0 .. chunk_count-1` is ignored by the receiver.

## This PC

The existing page stays on `127.0.0.1:8770`. Keys stay the same: H hover, 1 follow, 2 hold, L land, Esc disarm. Esc still disarms while a number field is focused. H, 1, 2, and L still do nothing while a number field is focused.

The Pi host field is removed. The page has an ESP32 host field and a connect control. Connect opens TCP to `host:8771`. The page shows receive fps, and whether video is arriving. The live image is a local MJPEG of the newest frame, with a box only while the latest finished detect pass still sees the tag.

### Video assembly

The desktop binds UDP `0.0.0.0:8765`.

Assembly state is one in-progress `frame_id` plus a set of received chunk indexes. A chunk whose `frame_id` differs from the in-progress id discards the partial frame and starts the new id. When every index from 0 to `chunk_count-1` is present, the JPEG is published once and that id is marked complete. Further chunks of a complete id are ignored. A partial frame is never decoded.

Width and height in the header must match the JPEG size. A mismatch drops the frame and sends the miss line.

### Detection

A single detect thread runs OpenCV ArUco, dictionary `DICT_APRILTAG_36h11`, accepting id 0 only. Parameters stay the current ones: one adaptive threshold window of 13, minimum marker perimeter rate 0.05.

The thread waits for the next complete frame newer than the one it last finished. If several complete frames arrived during a pass, it processes only the newest. Those skipped complete frames are not gaps: the newest result replaces the target, and no extra miss line is sent for them.

A gap is different. The desktop sends `PILOT <mode> 0 0 0 <w> <h>` as soon as either of these happens:

- A partial frame is discarded because a newer `frame_id` arrived.
- No complete frame has been published for 50 ms.

While the gap continues, that miss line is repeated every 50 ms. The next complete frame that contains id 0 replaces it with a hit. A finished pass that does not see id 0 also sends the miss line. Width and height on a miss line come from the newest chunk header, including a header from a frame that was discarded before the first successful decode. If no chunk header has arrived yet, no `PILOT` line is sent. `PING` does not carry a target and must not be what keeps the last pixel alive.

Host tests do not measure frames per second. On the bench the detect pass has to keep up with 30 complete 640×640 frames per second. The implementation does not add a GPU path.

Center is the mean of the four corners, rounded to an integer. Area is the shoelace area of those corners, rounded to an integer, in the streamed frame's pixels.

### Commands to the ESP32

TCP, `TCP_NODELAY`, one connection to port 8771. Lines are ASCII ending in `\n`. The desktop sends:

| When | Line |
|---|---|
| Every finished detect pass | `PILOT <mode> <cx> <cy> <area> <w> <h>` |
| Tag absent on that pass | `PILOT <mode> 0 0 0 <w> <h>` |
| H key | `CMD HOVER` and then the PILOT line |
| 1, 2, L, Esc | the PILOT line for `FOLLOW`, `HOLD`, `LAND`, or `DISARM` |
| Preset edit | `BIAS`, `CHASE`, `HTHR`, and `SAFE`, same field order as today |
| Every 100 ms while the browser is alive | `PING` |
| TCP session opens | `CMD DISARM` |

`PILOT` never arms. Only `CMD HOVER` arms. The first line of every new TCP session is `CMD DISARM`. Accepting the socket on the ESP32 does not itself change mode; this command does. The desktop sender's mode is `DISARM` until H. `<w>` and `<h>` always come from the last complete frame header. Until that header exists, the desktop sends no `PILOT` line.

The browser posts `/heartbeat` to the local desktop every 200 ms. The desktop sends `PING` every 100 ms only while a browser heartbeat has arrived in the last 1000 ms. If the browser has been silent for 1000 ms, the desktop sends `CMD DISARM` once and stops `PING`. If the desktop process itself dies, the ESP32's 500 ms rule is the hard stop.

The standoff field on the page, `area_stop_px2`, stays in 320-pixel units so existing numbers keep their meaning. The desktop sends

```text
SAFE <round(area_stop_px2 * (side / 320)^2)> <deadband_pct> <lpf_ms> <agl_ceiling_mm>
```

`side` is the width from the last complete frame. The scale is rounded to the nearest integer, with halves away from zero. The frame is square, so height is not a second scale. Deadband, slew, and stick gains are not scaled. They are already normalized by width and height in the chase law, or they are microseconds. `SAFE` is not sent until the first complete frame has provided `side`. An edit made before that is remembered and sent when `side` is known. `SAFE` is sent again when the frame side changes.

`STATE` lines from the ESP32 update mode, arm, stick values, and `agl_mm` on the page. `seen`, `cx`, and `cy` on the page come from the local detect pass, so the box matches the picture. `PONG` is ignored apart from proving the socket is alive.

## ESP32

Wi-Fi station on the hotspot. Credentials live in `esp32/main/wifi_secrets.h`, which is gitignored. The repo contains `esp32/main/wifi_secrets.example.h` with empty strings. If the SSID or password is empty, the firmware logs that Wi-Fi is not configured, does not connect, and stays disarmed. CRSF and the VL53 task still start.

The Pi UART task is removed. UART1 is not read and not written. CRSF stays on its own UART. The physical Pi-to-ESP32 wires may remain; the firmware does not use them.

A TCP server listens on port 8771. One client. A new connection closes the previous one. The socket accept itself does not change the flight mode. The desktop's first line, `CMD DISARM`, does. The socket is `TCP_NODELAY`.

Received lines go through the existing parser. `PILOT` now requires six fields after the word `PILOT`:

```text
PILOT <mode> <cx> <cy> <area> <w> <h>
```

Mode words remain `DISARM`, `HOVER`, `FOLLOW`, `HOLD`, and `LAND`. A line with a missing field, or with `w` or `h` less than or equal to 0, is ignored. `seen` is true when `cx`, `cy`, or `area` is non-zero. The parser stores `w` and `h` from the line. It does not force 320.

Any byte received from the TCP client refreshes the link timer. Bytes the ESP32 itself writes do not. If the timer has been started and 500 ms pass with no received byte, the mode becomes disarmed. The timer starts on the first received byte, so boot and a closed socket before the first command stay disarmed without a second disarm event. Closing the socket stops the heartbeats, so the same 500 ms rule disarms an aircraft that was armed.

The CRSF task stays pinned to core 1 at 100 Hz. The Wi-Fi and TCP task runs on core 0. The sensor task stays on core 0.

Every 50 ms the TCP task writes, if a client is connected:

```text
STATE <mode> <arm> <roll> <pitch> <thr> <yaw> <agl_mm>
```

`arm` is 1 when AUX1 is at least 1500. This is the same line the UART task used to send.

Chase math is unchanged aside from trusting `tag.w` and `tag.h`. A missing tag still zeroes every chase addition, including pitch and thrust. No coasting.

## Failure behavior

| Event | Result |
|---|---|
| UDP chunk missing, then a newer frame id | Partial frame discarded. Miss line sent immediately. Additions fall to bias. |
| No complete frame for 50 ms | Miss line, repeated every 50 ms until a complete frame is published. |
| Detect pass finds no id 0 | Miss line. Mode unchanged. Additions fall to bias. |
| Complete frames skipped because a newer complete frame is waiting | No miss line. The newest pass replaces the target. |
| Browser silent for 1000 ms | Desktop sends `CMD DISARM` once and stops `PING`. |
| TCP silent for 500 ms | Disarm. Throttle minimum, arm switch low. |
| Second TCP client | First socket closed. Mode unchanged until a command arrives. The new session starts with `CMD DISARM`. |
| Wi-Fi drops | Reconnect. Silence still disarms after 500 ms. |
| Desktop process restart | Sender comes up in `DISARM`. ESP32 disarms on the silence, if it was armed, before the new link exists. |

## Tests

Props stay off. Nothing in this branch flashes the ESP32 or images the Pi.

Desktop, `python -m pytest -q` in `desktop/`:

- A full set of chunks for one `frame_id` becomes one JPEG.
- A missing chunk does not publish.
- A chunk with a new `frame_id` drops the partial frame.
- A repeated chunk of an already complete id does not publish again.
- Discarding a partial frame writes `PILOT <mode> 0 0 0 <w> <h>`.
- `area_stop_px2` of 1000 at side 640 is sent as `SAFE` with area 4000. At side 320 it is sent as 1000. `SAFE` is not written before a frame side is known.
- The H command writes `CMD HOVER` and then a `PILOT HOVER` line. A `PILOT` line is never the arm command.
- A new TCP session's first line is `CMD DISARM`.
- Esc writes a `PILOT DISARM` line.
- When the last browser heartbeat is older than 1000 ms, the sender writes `CMD DISARM` and does not write `PING`.

Pi, `python -m pytest -q` in `pi/`:

- Given two published frames before the sender runs, only the later frame is encoded and sent.
- Chunk headers carry the magic, the frame id, and indexes covering the JPEG with 1400-byte payloads except the tail.

ESP32 host chase test still prints `chase ok`. Add one case: a tag at the center of a 640×640 frame produces the same stick command as the center of a 320×320 frame, and an `area_stop_px2` of 4000 against a tag area of 4000 holds the standoff at the stop point. `idf.py build` completes. The binary is not flashed.

## Out of scope

- YOLO or any other neural detector.
- CUDA or the 5090.
- Running AprilTag on the Pi or on the IMX500 neural block.
- A runtime switch back to the UART stack. That stack remains on `main`.
- Flashing the ESP32, reflashing the Pi, or arming the aircraft.
- Optical flow, position hold, PMW3901, or TF-Luna.
