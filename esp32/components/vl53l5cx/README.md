# VL53L5CX ULD (vendored)

ST VL53L5CX Ultra Lite Driver v2.0.0, adapted from
[RJRP44/VL53L5CX-Library](https://github.com/RJRP44/VL53L5CX-Library) (BSD-3-Clause).

Platform I2C glue lives in `main/vl53l5cx_port.c` on the shared pilot ToF bus.

Disable forward ranging via `idf.py menuconfig` → **Pilot ToF sensors** →
**Enable VL53L5CX forward summary range** (`CONFIG_TOF_L5CX_ENABLE`).
