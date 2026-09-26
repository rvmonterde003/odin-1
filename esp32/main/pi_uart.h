#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t pi_uart_init(void);
void pi_uart_send_line(const char *line);
void pi_uart_task(void *arg);

#ifdef __cplusplus
}
#endif
