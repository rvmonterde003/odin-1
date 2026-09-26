#include "vl53l5cx_port.h"

#include "pinout.h"
#include "vl53l5cx_api.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <string.h>

static const char *TAG = "vl53l5cx";

#define ADDR_L5CX_7BIT      0x29
#define L5CX_I2C_TIMEOUT_MS 100
#define L5CX_RANGING_HZ     10
#define ZONE_A              59U
#define ZONE_B              60U

static VL53L5CX_Configuration s_dev;
static bool s_ready;

static int i2c_to_uld(esp_err_t err)
{
    return (err == ESP_OK) ? 0 : 255;
}

uint8_t VL53L5CX_WrMulti(VL53L5CX_Platform *p_platform, uint16_t RegisterAdress, uint8_t *p_values, uint32_t size)
{
    i2c_master_transmit_multi_buffer_info_t bufs[2];
    uint8_t reg[2] = {(uint8_t)(RegisterAdress >> 8), (uint8_t)RegisterAdress};

    bufs[0].write_buffer = reg;
    bufs[0].buffer_size = 2;
    bufs[1].write_buffer = p_values;
    bufs[1].buffer_size = size;

    return i2c_to_uld(i2c_master_multi_buffer_transmit(p_platform->handle, bufs, 2, L5CX_I2C_TIMEOUT_MS));
}

uint8_t VL53L5CX_WrByte(VL53L5CX_Platform *p_platform, uint16_t RegisterAdress, uint8_t value)
{
    return VL53L5CX_WrMulti(p_platform, RegisterAdress, &value, 1);
}

uint8_t VL53L5CX_RdMulti(VL53L5CX_Platform *p_platform, uint16_t RegisterAdress, uint8_t *p_values, uint32_t size)
{
    uint8_t reg[2] = {(uint8_t)(RegisterAdress >> 8), (uint8_t)RegisterAdress};
    return i2c_to_uld(i2c_master_transmit_receive(p_platform->handle, reg, sizeof(reg), p_values, size,
                                                  L5CX_I2C_TIMEOUT_MS));
}

uint8_t VL53L5CX_RdByte(VL53L5CX_Platform *p_platform, uint16_t RegisterAdress, uint8_t *p_value)
{
    return VL53L5CX_RdMulti(p_platform, RegisterAdress, p_value, 1);
}

uint8_t VL53L5CX_Reset_Sensor(VL53L5CX_Platform *p_platform)
{
    gpio_set_level(p_platform->reset_gpio, 0);
    VL53L5CX_WaitMs(p_platform, 100);
    gpio_set_level(p_platform->reset_gpio, 1);
    VL53L5CX_WaitMs(p_platform, 100);
    return 0;
}

void VL53L5CX_SwapBuffer(uint8_t *buffer, uint16_t size)
{
    for (uint16_t i = 0; i < size; i += 4) {
        uint8_t tmp[4] = {buffer[i + 3], buffer[i + 2], buffer[i + 1], buffer[i]};
        memcpy(&buffer[i], tmp, 4);
    }
}

uint8_t VL53L5CX_WaitMs(VL53L5CX_Platform *p_platform, uint32_t TimeMs)
{
    (void)p_platform;
    vTaskDelay(pdMS_TO_TICKS(TimeMs));
    return 0;
}

static bool target_valid(uint8_t status)
{
    return status == 5U || status == 9U;
}

static int16_t zone_mm(const VL53L5CX_ResultsData *results, uint8_t zone)
{
    if (zone >= VL53L5CX_RESOLUTION_8X8) {
        return -1;
    }
    if (!target_valid(results->target_status[zone])) {
        return -1;
    }
    int16_t mm = (int16_t)results->distance_mm[zone];
    if (mm <= 0) {
        return -1;
    }
    return mm;
}

static int32_t agl_from_zones(const VL53L5CX_ResultsData *results)
{
    int16_t a = zone_mm(results, ZONE_A);
    int16_t b = zone_mm(results, ZONE_B);
    if (a >= 0 && b >= 0) {
        return (int32_t)(((int32_t)a + (int32_t)b) / 2);
    }
    if (a >= 0) {
        return (int32_t)a;
    }
    if (b >= 0) {
        return (int32_t)b;
    }
    return -1;
}

esp_err_t vl53l5cx_port_init(i2c_master_bus_handle_t bus)
{
    s_ready = false;
    memset(&s_dev, 0, sizeof(s_dev));

    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = ADDR_L5CX_7BIT,
        .scl_speed_hz = I2C_FREQ_HZ,
    };

    esp_err_t err = i2c_master_bus_add_device(bus, &dev_cfg, &s_dev.platform.handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2C attach 0x%02X failed: %s", ADDR_L5CX_7BIT, esp_err_to_name(err));
        return err;
    }

    s_dev.platform.address = VL53L5CX_DEFAULT_I2C_ADDRESS;
    s_dev.platform.reset_gpio = PIN_XSHUT_L5CX;

    uint8_t alive = 0;
    if (vl53l5cx_is_alive(&s_dev, &alive) != 0 || !alive) {
        ESP_LOGE(TAG, "sensor not detected at 0x%02X", ADDR_L5CX_7BIT);
        i2c_master_bus_rm_device(s_dev.platform.handle);
        s_dev.platform.handle = NULL;
        return ESP_ERR_NOT_FOUND;
    }

    if (vl53l5cx_init(&s_dev) != 0) {
        ESP_LOGE(TAG, "ULD init failed");
        i2c_master_bus_rm_device(s_dev.platform.handle);
        s_dev.platform.handle = NULL;
        return ESP_FAIL;
    }

    if (vl53l5cx_set_resolution(&s_dev, VL53L5CX_RESOLUTION_8X8) != 0) {
        ESP_LOGE(TAG, "set 8x8 resolution failed");
        i2c_master_bus_rm_device(s_dev.platform.handle);
        s_dev.platform.handle = NULL;
        return ESP_FAIL;
    }

    if (vl53l5cx_set_ranging_frequency_hz(&s_dev, L5CX_RANGING_HZ) != 0) {
        ESP_LOGW(TAG, "set %d Hz failed; using default rate", L5CX_RANGING_HZ);
    }

    if (vl53l5cx_start_ranging(&s_dev) != 0) {
        ESP_LOGE(TAG, "start ranging failed");
        i2c_master_bus_rm_device(s_dev.platform.handle);
        s_dev.platform.handle = NULL;
        return ESP_FAIL;
    }

    s_ready = true;
    ESP_LOGI(TAG, "8x8 ready addr=0x%02X zones %u+%u", ADDR_L5CX_7BIT, ZONE_A, ZONE_B);
    return ESP_OK;
}

bool vl53l5cx_port_poll(int32_t *agl_mm)
{
    if (!agl_mm || !s_ready) {
        return false;
    }

    uint8_t data_ready = 0;
    if (vl53l5cx_check_data_ready(&s_dev, &data_ready) != 0 || !data_ready) {
        return false;
    }

    VL53L5CX_ResultsData results;
    if (vl53l5cx_get_ranging_data(&s_dev, &results) != 0) {
        return false;
    }

    *agl_mm = agl_from_zones(&results);
    return true;
}
