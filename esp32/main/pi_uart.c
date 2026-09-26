#include "pi_uart.h"
#include "pinout.h"
#include "cmd_parser.h"
#include "flight_state.h"

#include "driver/uart.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <stdio.h>
#include <string.h>

esp_err_t pi_uart_init(void)
{
    uart_config_t cfg = {
        .baud_rate = PI_UART_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(PI_UART_PORT, 2048, 2048, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(PI_UART_PORT, &cfg));
    ESP_ERROR_CHECK(uart_set_pin(PI_UART_PORT, PIN_PI_UART_TX, PIN_PI_UART_RX,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    return ESP_OK;
}

void pi_uart_send_line(const char *line)
{
    if (!line) {
        return;
    }
    uart_write_bytes(PI_UART_PORT, line, strlen(line));
    uart_write_bytes(PI_UART_PORT, "\n", 1);
}

void pi_uart_task(void *arg)
{
    (void)arg;
    uint8_t data[128];
    char line[160];
    size_t line_len = 0;
    char reply[32];
    TickType_t last_telem = xTaskGetTickCount();
    const TickType_t telem_period = pdMS_TO_TICKS(1000 / TELEMETRY_HZ);

    for (;;) {
        int n = uart_read_bytes(PI_UART_PORT, data, sizeof(data), pdMS_TO_TICKS(20));
        for (int i = 0; i < n; i++) {
            char c = (char)data[i];
            if (c == '\r') {
                continue;
            }
            if (c == '\n') {
                line[line_len] = '\0';
                if (line_len > 0) {
                    cmd_parse_line(line, reply, sizeof(reply));
                    if (reply[0]) {
                        pi_uart_send_line(reply);
                    }
                }
                line_len = 0;
            } else if (line_len + 1 < sizeof(line)) {
                line[line_len++] = c;
            } else {
                line_len = 0;
            }
        }

        TickType_t now = xTaskGetTickCount();
        if ((now - last_telem) >= telem_period) {
            last_telem = now;
            flight_state_lock();
            flight_state_t *s = flight_state_ptr();
            char telem[96];
            int arm = (s->aux1 >= 1500) ? 1 : 0;
            snprintf(telem, sizeof(telem), "STATE %s %d %u %u %u %u %ld",
                     odin_mode_str(s->mode),
                     arm,
                     (unsigned)s->roll,
                     (unsigned)s->pitch,
                     (unsigned)s->throttle,
                     (unsigned)s->yaw,
                     (long)s->agl_mm);
            flight_state_unlock();
            pi_uart_send_line(telem);
        }
    }
}
