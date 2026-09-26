#include "crsf_tx.h"
#include "pinout.h"

#include "driver/uart.h"
#include "driver/gpio.h"
#include <string.h>

#define CRSF_SYNC                 0xC8
#define CRSF_FRAMETYPE_RC_CHANNELS 0x16

static uint8_t crsf_crc8(const uint8_t *data, int len)
{
    uint8_t crc = 0;
    for (int i = 0; i < len; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++) {
            if (crc & 0x80) {
                crc = (uint8_t)((crc << 1) ^ 0xD5);
            } else {
                crc <<= 1;
            }
        }
    }
    return crc;
}

static uint16_t us_to_crsf(uint16_t us)
{
    if (us < 1000) {
        us = 1000;
    }
    if (us > 2000) {
        us = 2000;
    }
    return (uint16_t)(191 + ((uint32_t)(us - 1000) * (1792 - 191)) / 1000);
}

esp_err_t crsf_tx_init(void)
{
    uart_config_t cfg = {
        .baud_rate = CRSF_UART_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(CRSF_UART_PORT, 512, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(CRSF_UART_PORT, &cfg));
    const int rx_pin = (PIN_CRSF_RX < 0) ? UART_PIN_NO_CHANGE : PIN_CRSF_RX;
    ESP_ERROR_CHECK(uart_set_pin(CRSF_UART_PORT, PIN_CRSF_TX, rx_pin,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    return ESP_OK;
}

void crsf_tx_send_rc(const uint16_t ch_us[16])
{
    uint16_t ch[16];
    for (int i = 0; i < 16; i++) {
        ch[i] = us_to_crsf(ch_us[i]);
    }

    uint8_t payload[22];
    memset(payload, 0, sizeof(payload));

    uint32_t bit_buf = 0;
    int bit_count = 0;
    int out = 0;
    for (int i = 0; i < 16; i++) {
        bit_buf |= ((uint32_t)(ch[i] & 0x07FF)) << bit_count;
        bit_count += 11;
        while (bit_count >= 8) {
            payload[out++] = (uint8_t)(bit_buf & 0xFF);
            bit_buf >>= 8;
            bit_count -= 8;
        }
    }
    if (bit_count > 0 && out < 22) {
        payload[out++] = (uint8_t)(bit_buf & 0xFF);
    }

    uint8_t frame[26];
    frame[0] = CRSF_SYNC;
    frame[1] = 24;
    frame[2] = CRSF_FRAMETYPE_RC_CHANNELS;
    memcpy(&frame[3], payload, 22);
    frame[25] = crsf_crc8(&frame[2], 23);

    uart_write_bytes(CRSF_UART_PORT, (const char *)frame, sizeof(frame));
}
