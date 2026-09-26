#pragma once

#include "chase.h"

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    odin_mode_t mode;
    chase_params_t chase;
    tag_state_t tag;
    hold_state_t hold;
    slew_state_t slew;

    uint16_t roll;
    uint16_t pitch;
    uint16_t yaw;
    uint16_t throttle;
    uint16_t aux1;
    uint16_t aux2;
    uint16_t aux3;
    uint16_t aux4;

    int32_t agl_mm;
    uint32_t last_pi_ms;
} flight_state_t;

void flight_state_init(void);
void flight_state_lock(void);
void flight_state_unlock(void);
flight_state_t *flight_state_ptr(void);

uint32_t flight_now_ms(void);

#ifdef __cplusplus
}
#endif
