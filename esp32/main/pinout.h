#pragma once

/* Odin-2 wiring — see odin-2/SPEC.md */

/* Pi link UART (ASCII @ 115200) */
#define PIN_PI_UART_TX   17
#define PIN_PI_UART_RX   16
#define PI_UART_PORT     UART_NUM_1
#define PI_UART_BAUD     115200

/* CRSF to flight controller (TX only) */
#define PIN_CRSF_TX      27
#define PIN_CRSF_RX      (-1)
#define CRSF_UART_PORT   UART_NUM_2
#define CRSF_UART_BAUD   420000

/* I2C ToF bus */
#define PIN_I2C_SDA      21
#define PIN_I2C_SCL      22
#define I2C_PORT_NUM     I2C_NUM_0
#define I2C_FREQ_HZ      400000

#define PIN_XSHUT_L5CX   25
#define PIN_XSHUT_L1X_L  26
#define PIN_XSHUT_L1X_R  33

#define CRSF_TASK_HZ        100
#define TELEMETRY_HZ        20
#define SENSORS_TASK_HZ     15
#define PI_FAILSAFE_MS      500
