#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    ODIN_MODE_DISARMED = 0,
    ODIN_MODE_HOVER,
    ODIN_MODE_CHASE,
    ODIN_MODE_HOLD,
    ODIN_MODE_LAND,
} odin_mode_t;

typedef struct {
    int bias_roll_us;
    int bias_pitch_us;
    int bias_yaw_us;
    int bias_thrust_us;
    int yaw_max_us;
    int roll_max_us;
    int pitch_min_us;
    int pitch_max_us;
    int thrust_target_us;
    int yaw_slew_us_s;
    int roll_slew_us_s;
    int pitch_slew_us_s;
    int thrust_slew_us_s;
    int hover_thrust_us;
    int hover_slew_us_s;
    int land_thrust_us;
    int land_slew_us_s;
    int action_thrust_us;
    int action_slew_us_s;
    /* Safety / smoothing (SAFE line). 0 disables area_stop, lpf_ms, agl_ceiling_mm. */
    int area_stop_px2;      /* FOLLOW: pitch fades to 0 as tag area reaches this; brakes past it */
    int deadband_pct;       /* % of half-frame around centre where yaw/roll/thrust additions are 0 */
    int lpf_ms;             /* first-order low-pass on FOLLOW/HOLD targets before the slew */
    int agl_ceiling_mm;     /* above this AGL, throttle may not exceed hover_thrust_us */
} chase_params_t;

/* Hard firmware limits. No preset can push a stick past these. */
#define HARD_ROLL_MIN_US    1350
#define HARD_ROLL_MAX_US    1650
#define HARD_PITCH_MIN_US   1350
#define HARD_PITCH_MAX_US   1650
#define HARD_YAW_MIN_US     1380
#define HARD_YAW_MAX_US     1620
#define HARD_THR_MAX_US     1650
/* Past area_stop the pitch addition goes negative to brake, capped at this share of pitch_max. */
#define STANDOFF_BRAKE_MAX  0.5f

#define TAG_STALE_MS 300

typedef struct {
    int seen;
    int cx;
    int cy;
    int area;
    int w;
    int h;
    uint32_t last_ms;
} tag_state_t;

#define HOLD_SAMPLE_DELAY_MS 1500

typedef struct {
    uint32_t enter_ms;
    int ref_area;
} hold_state_t;

typedef struct {
    int32_t roll_rem;
    int32_t pitch_rem;
    int32_t yaw_rem;
    int32_t thr_rem;
    int32_t action_rem;
    uint16_t action_us;
    /* Low-pass state for FOLLOW/HOLD targets. lpf_valid 0 = seed on next tick. */
    float roll_f;
    float pitch_f;
    float yaw_f;
    float thr_f;
    int lpf_valid;
} slew_state_t;

void chase_params_set_defaults(chase_params_t *p);
void slew_state_init(slew_state_t *s);
void hold_state_init(hold_state_t *h);

uint16_t chase_clamp_us(int v);

void chase_hold_step(hold_state_t *hold, odin_mode_t mode, uint32_t now_ms, const tag_state_t *tag);

void chase_desired_sticks(odin_mode_t mode,
                          const chase_params_t *p,
                          const tag_state_t *tag,
                          hold_state_t *hold,
                          uint32_t now_ms,
                          uint16_t *roll,
                          uint16_t *pitch,
                          uint16_t *yaw,
                          uint16_t *thr);

uint16_t chase_slew_axis(uint16_t cur, uint16_t target, uint32_t slew_us_s, int32_t *rem);

void chase_apply_disarm_outputs(uint16_t *thr, uint16_t *aux1, uint16_t *aux3);

/* Clamp every stick to the HARD_* window. Applied last, after slew and action thrust. */
void chase_hard_limit(uint16_t *roll, uint16_t *pitch, uint16_t *yaw, uint16_t *thr);

/* AGL ceiling: when agl_mm is valid and at/above agl_ceiling_mm, throttle is capped at
 * hover_thrust_us. Only ever removes thrust. Not part of the stick law. */
uint16_t chase_apply_ceiling(uint16_t thr, const chase_params_t *p, int32_t agl_mm);

/* Low-pass one target. tau_ms 0 = passthrough. dt is the CRSF tick. */
uint16_t chase_lpf_axis(float *state, int *valid, uint16_t target, int tau_ms);

void chase_stick_tick(odin_mode_t mode,
                      const chase_params_t *p,
                      const tag_state_t *tag,
                      hold_state_t *hold,
                      slew_state_t *slew,
                      bool disarm_snap,
                      uint16_t *roll,
                      uint16_t *pitch,
                      uint16_t *yaw,
                      uint16_t *thr,
                      uint16_t *aux1,
                      uint16_t *aux2,
                      uint16_t *aux3,
                      uint32_t now_ms);

const char *odin_mode_str(odin_mode_t m);

#ifdef __cplusplus
}
#endif
