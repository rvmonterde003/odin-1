#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t sensors_init(void);
void sensors_task(void *arg);

#ifdef __cplusplus
}
#endif
