#include "sensors.h"
#include "vl53l5cx_port.h"
#include "flight_state.h"
#include "pinout.h"

#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "sensors";

static i2c_master_bus_handle_t s_i2c_bus;
static bool s_l5cx_ok;

static void l1x_xshut_hold_low(void)
{
    gpio_config_t cfg = {
        .pin_bit_mask = (1ULL << PIN_XSHUT_L1X_L) | (1ULL << PIN_XSHUT_L1X_R),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&cfg));
    gpio_set_level(PIN_XSHUT_L1X_L, 0);
    gpio_set_level(PIN_XSHUT_L1X_R, 0);
}

static void l5cx_xshut_prepare(void)
{
    gpio_config_t cfg = {
        .pin_bit_mask = (1ULL << PIN_XSHUT_L5CX),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&cfg));
    gpio_set_level(PIN_XSHUT_L5CX, 1);
}

esp_err_t sensors_init(void)
{
    s_l5cx_ok = false;

    l1x_xshut_hold_low();
    vTaskDelay(pdMS_TO_TICKS(10));

    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = I2C_PORT_NUM,
        .sda_io_num = PIN_I2C_SDA,
        .scl_io_num = PIN_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };

    esp_err_t err = i2c_new_master_bus(&bus_cfg, &s_i2c_bus);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2C bus init failed: %s", esp_err_to_name(err));
        return err;
    }

    l5cx_xshut_prepare();
    vTaskDelay(pdMS_TO_TICKS(10));

    if (vl53l5cx_port_init(s_i2c_bus) == ESP_OK) {
        s_l5cx_ok = true;
        ESP_LOGI(TAG, "VL53L5CX online SDA=%d SCL=%d", PIN_I2C_SDA, PIN_I2C_SCL);
    } else {
        ESP_LOGW(TAG, "VL53L5CX init failed — agl_mm stays -1");
    }

    return ESP_OK;
}

void sensors_task(void *arg)
{
    (void)arg;
    const TickType_t period = pdMS_TO_TICKS(1000 / SENSORS_TASK_HZ);
    TickType_t last = xTaskGetTickCount();

    for (;;) {
        if (s_l5cx_ok) {
            int32_t agl = -1;
            if (vl53l5cx_port_poll(&agl)) {
                flight_state_lock();
                flight_state_ptr()->agl_mm = agl;
                flight_state_unlock();
            }
        }
        vTaskDelayUntil(&last, period);
    }
}
