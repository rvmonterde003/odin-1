#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t crsf_tx_init(void);
void crsf_tx_send_rc(const uint16_t ch[16]);

#ifdef __cplusplus
}
#endif
