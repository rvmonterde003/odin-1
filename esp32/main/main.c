#include "pinout.h"
#include "flight_state.h"
#include "pi_uart.h"
#include "crsf_tx.h"
#include "sensors.h"
#include "chase.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"

static const char *TAG = "odin2";

static void apply_pi_failsafe(flight_state_t *s)
{
    if (s->last_pi_ms == 0) {
        return;
    }
    if ((flight_now_ms() - s->last_pi_ms) > PI_FAILSAFE_MS) {
        s->mode = ODIN_MODE_DISARMED;
    }
}

static void crsf_pilot_task(void *arg)
{
    (void)arg;
    const TickType_t period = pdMS_TO_TICKS(1000 / CRSF_TASK_HZ);
    TickType_t last = xTaskGetTickCount();
    odin_mode_t prev_mode = ODIN_MODE_DISARMED;
    uint16_t ch[16];

    for (;;) {
        flight_state_lock();
        flight_state_t *s = flight_state_ptr();
        apply_pi_failsafe(s);

        bool disarm_snap = (s->mode == ODIN_MODE_DISARMED && prev_mode != ODIN_MODE_DISARMED);

        chase_stick_tick(s->mode,
                         &s->chase,
                         &s->tag,
                         &s->hold,
                         &s->slew,
                         disarm_snap,
                         &s->roll,
                         &s->pitch,
                         &s->yaw,
                         &s->throttle,
                         &s->aux1,
                         &s->aux2,
                         &s->aux3,
                         flight_now_ms());

        /* Safety clamp outside the stick law: only ever lowers throttle. */
        s->throttle = chase_apply_ceiling(s->throttle, &s->chase, s->agl_mm);

        for (int i = 0; i < 16; i++) {
            ch[i] = 1500;
        }
        ch[0] = s->roll;
        ch[1] = s->pitch;
        ch[2] = s->throttle;
        ch[3] = s->yaw;
        ch[4] = s->aux1;
        ch[5] = s->aux2;
        ch[6] = s->aux3;
        ch[7] = s->aux4;

        prev_mode = s->mode;
        flight_state_unlock();

        crsf_tx_send_rc(ch);
        vTaskDelayUntil(&last, period);
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "odin2 starting");
    flight_state_init();
    ESP_ERROR_CHECK(pi_uart_init());
    ESP_ERROR_CHECK(crsf_tx_init());

    if (sensors_init() != ESP_OK) {
        ESP_LOGW(TAG, "sensors init partial failure");
    }

    xTaskCreatePinnedToCore(pi_uart_task, "pi_uart", 6144, NULL, 5, NULL, 0);
    xTaskCreatePinnedToCore(sensors_task, "sensors", 8192, NULL, 6, NULL, 0);
    xTaskCreatePinnedToCore(crsf_pilot_task, "crsf_pilot", 4096, NULL, 8, NULL, 1);

    ESP_LOGI(TAG, "tasks running Pi %d CRSF %d sensors %d Hz",
             PI_UART_BAUD, CRSF_UART_BAUD, SENSORS_TASK_HZ);
}
