#pragma once

#include "driver/i2c_master.h"
#include "esp_err.h"
#include <stdbool.h>
#include <stdint.h>

esp_err_t vl53l5cx_port_init(i2c_master_bus_handle_t bus);
bool vl53l5cx_port_poll(int32_t *agl_mm);
