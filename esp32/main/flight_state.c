#include "flight_state.h"

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "esp_timer.h"

static flight_state_t g_state;
static SemaphoreHandle_t g_mu;

void flight_state_init(void)
{
    g_mu = xSemaphoreCreateMutex();

    g_state.mode = ODIN_MODE_DISARMED;
    chase_params_set_defaults(&g_state.chase);
    g_state.tag.seen = 0;
    g_state.tag.cx = 0;
    g_state.tag.cy = 0;
    g_state.tag.w = 320;
    g_state.tag.h = 320;
    g_state.tag.last_ms = 0;
    g_state.tag.area = 0;
    hold_state_init(&g_state.hold);
    slew_state_init(&g_state.slew);

    g_state.roll = (uint16_t)g_state.chase.bias_roll_us;
    g_state.pitch = (uint16_t)g_state.chase.bias_pitch_us;
    g_state.yaw = (uint16_t)g_state.chase.bias_yaw_us;
    g_state.throttle = 1000;
    g_state.aux1 = 1000;
    g_state.aux2 = 1000;
    g_state.aux3 = 1000;
    g_state.aux4 = 1500;

    g_state.agl_mm = -1;
    g_state.last_pi_ms = 0;
}

void flight_state_lock(void)
{
    xSemaphoreTake(g_mu, portMAX_DELAY);
}

void flight_state_unlock(void)
{
    xSemaphoreGive(g_mu);
}

flight_state_t *flight_state_ptr(void)
{
    return &g_state;
}

uint32_t flight_now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000ULL);
}
