#include "chase.h"
#include "pinout.h"

#include <stddef.h>

uint16_t chase_clamp_us(int v)
{
    if (v < 1000) {
        return 1000;
    }
    if (v > 2000) {
        return 2000;
    }
    return (uint16_t)v;
}

void chase_params_set_defaults(chase_params_t *p)
{
    if (!p) {
        return;
    }
    p->bias_roll_us = 1500;
    p->bias_pitch_us = 1500;
    p->bias_yaw_us = 1500;
    p->bias_thrust_us = 1350;
    p->yaw_max_us = 80;
    p->roll_max_us = 30;
    p->pitch_min_us = 0;
    p->pitch_max_us = 120;
    p->thrust_target_us = 40;
    p->yaw_slew_us_s = 400;
    p->roll_slew_us_s = 200;
    p->pitch_slew_us_s = 300;
    p->thrust_slew_us_s = 250;
    p->hover_thrust_us = 1350;
    p->hover_slew_us_s = 2500;
    p->land_thrust_us = 1100;
    p->land_slew_us_s = 2500;
    p->action_thrust_us = 0;
    p->action_slew_us_s = 250;
    p->area_stop_px2 = 0;
    p->deadband_pct = 10;
    p->lpf_ms = 150;
    p->agl_ceiling_mm = 0;
}

void slew_state_init(slew_state_t *s)
{
    if (!s) {
        return;
    }
    s->roll_rem = 0;
    s->pitch_rem = 0;
    s->yaw_rem = 0;
    s->thr_rem = 0;
    s->action_rem = 0;
    s->action_us = 0;
    s->roll_f = 0.0f;
    s->pitch_f = 0.0f;
    s->yaw_f = 0.0f;
    s->thr_f = 0.0f;
    s->lpf_valid = 0;
}

void hold_state_init(hold_state_t *h)
{
    if (!h) {
        return;
    }
    h->enter_ms = 0;
    h->ref_area = 0;
}

void chase_hold_step(hold_state_t *hold, odin_mode_t mode, uint32_t now_ms, const tag_state_t *tag)
{
    static odin_mode_t prev_mode = ODIN_MODE_DISARMED;

    if (!hold) {
        prev_mode = mode;
        return;
    }

    if (mode == ODIN_MODE_HOLD && prev_mode != ODIN_MODE_HOLD) {
        hold->enter_ms = now_ms;
        hold->ref_area = 0;
    }
    prev_mode = mode;

    if (mode != ODIN_MODE_HOLD || hold->ref_area != 0) {
        return;
    }
    if (!tag || !tag->seen || tag->area <= 0) {
        return;
    }
    if ((now_ms - hold->enter_ms) >= HOLD_SAMPLE_DELAY_MS) {
        hold->ref_area = tag->area;
    }
}

static float clamp_f(float v, float lo, float hi)
{
    if (v < lo) {
        return lo;
    }
    if (v > hi) {
        return hi;
    }
    return v;
}

static int chase_frame_ok(const tag_state_t *tag)
{
    if (!tag || !tag->seen) {
        return 0;
    }
    return tag->w > 0 && tag->h > 0;
}

/* Dead zone with rescale: 0 inside +-db, continuous, still +-1 at the frame edge. */
static float apply_deadband(float v, float db)
{
    if (db <= 0.0f || db >= 1.0f) {
        return v;
    }
    float a = v >= 0.0f ? v : -v;
    if (a <= db) {
        return 0.0f;
    }
    float out = (a - db) / (1.0f - db);
    return v >= 0.0f ? out : -out;
}

static void chase_frame_norm(const chase_params_t *p, const tag_state_t *tag,
                             float *nx, float *ny, float *ax)
{
    float x = ((float)tag->cx - (float)tag->w * 0.5f) / ((float)tag->w * 0.5f);
    float y = ((float)tag->cy - (float)tag->h * 0.5f) / ((float)tag->h * 0.5f);
    x = clamp_f(x, -1.0f, 1.0f);
    y = clamp_f(y, -1.0f, 1.0f);
    float db = p ? (float)p->deadband_pct / 100.0f : 0.0f;
    /* ax (pitch fade) keeps the raw offset so pitch still eases off toward the edge. */
    *ax = x >= 0.0f ? x : -x;
    *nx = apply_deadband(x, db);
    *ny = apply_deadband(y, db);
}

/* FOLLOW standoff: 1 when far, 0 at area_stop, down to -STANDOFF_BRAKE_MAX when closer. */
static float standoff_scale(const chase_params_t *p, const tag_state_t *tag)
{
    if (!p || p->area_stop_px2 <= 0 || !tag || tag->area <= 0) {
        return 1.0f;
    }
    float s = 1.0f - (float)tag->area / (float)p->area_stop_px2;
    return clamp_f(s, -STANDOFF_BRAKE_MAX, 1.0f);
}

static void chase_follow_additions(const chase_params_t *p, const tag_state_t *tag,
                                   int *roll_add, int *pitch_add, int *yaw_add, int *thr_add)
{
    *roll_add = 0;
    *pitch_add = 0;
    *yaw_add = 0;
    *thr_add = 0;

    if (!p || !chase_frame_ok(tag)) {
        return;
    }

    float nx;
    float ny;
    float ax;
    chase_frame_norm(p, tag, &nx, &ny, &ax);

    *yaw_add = (int)(nx * (float)p->yaw_max_us);
    *roll_add = (int)(nx * (float)p->roll_max_us);
    float pitch_base = (float)p->pitch_max_us +
                       ((float)p->pitch_min_us - (float)p->pitch_max_us) * ax;
    *pitch_add = (int)(pitch_base * standoff_scale(p, tag));
    *thr_add = (int)(-ny * (float)p->thrust_target_us);
}

static void chase_hold_additions(const chase_params_t *p,
                                 const tag_state_t *tag,
                                 const hold_state_t *hold,
                                 uint32_t now_ms,
                                 int *roll_add,
                                 int *pitch_add,
                                 int *yaw_add)
{
    *roll_add = 0;
    *pitch_add = 0;
    *yaw_add = 0;

    if (!p || !chase_frame_ok(tag)) {
        return;
    }

    float nx;
    float ny;
    float ax;
    chase_frame_norm(p, tag, &nx, &ny, &ax);
    (void)ax;

    *yaw_add = (int)(nx * (float)p->yaw_max_us);
    *roll_add = (int)(nx * (float)p->roll_max_us);

    if (!hold || hold->ref_area <= 0) {
        return;
    }
    if ((now_ms - hold->enter_ms) < HOLD_SAMPLE_DELAY_MS) {
        return;
    }

    float delta = (float)tag->area / (float)hold->ref_area - 1.0f;
    delta = clamp_f(delta, -1.0f, 1.0f);
    *pitch_add = (int)(-delta * (float)p->pitch_max_us);
}

static int chase_tilt_commanded(odin_mode_t mode,
                                const chase_params_t *p,
                                const tag_state_t *tag,
                                const hold_state_t *hold,
                                uint32_t now_ms)
{
    int roll_add = 0;
    int pitch_add = 0;
    int yaw_add = 0;
    int thr_add = 0;

    if (mode == ODIN_MODE_CHASE) {
        chase_follow_additions(p, tag, &roll_add, &pitch_add, &yaw_add, &thr_add);
    } else if (mode == ODIN_MODE_HOLD) {
        chase_hold_additions(p, tag, hold, now_ms, &roll_add, &pitch_add, &yaw_add);
    } else {
        return 0;
    }
    (void)yaw_add;
    (void)thr_add;
    return roll_add != 0 || pitch_add != 0;
}

void chase_desired_sticks(odin_mode_t mode,
                          const chase_params_t *p,
                          const tag_state_t *tag,
                          hold_state_t *hold,
                          uint32_t now_ms,
                          uint16_t *roll,
                          uint16_t *pitch,
                          uint16_t *yaw,
                          uint16_t *thr)
{
    if (!p || !roll || !pitch || !yaw || !thr) {
        return;
    }

    int roll_add = 0;
    int pitch_add = 0;
    int yaw_add = 0;
    int thr_add = 0;

    if (mode == ODIN_MODE_CHASE) {
        chase_follow_additions(p, tag, &roll_add, &pitch_add, &yaw_add, &thr_add);
    } else if (mode == ODIN_MODE_HOLD) {
        chase_hold_additions(p, tag, hold, now_ms, &roll_add, &pitch_add, &yaw_add);
    }

    if (mode == ODIN_MODE_DISARMED) {
        *roll = chase_clamp_us(p->bias_roll_us);
        *pitch = chase_clamp_us(p->bias_pitch_us);
        *yaw = chase_clamp_us(p->bias_yaw_us);
        *thr = 1000;
        return;
    }

    if (mode == ODIN_MODE_LAND) {
        *roll = chase_clamp_us(p->bias_roll_us);
        *pitch = chase_clamp_us(p->bias_pitch_us);
        *yaw = chase_clamp_us(p->bias_yaw_us);
        *thr = chase_clamp_us(p->land_thrust_us);
        return;
    }

    if (mode == ODIN_MODE_HOVER || mode == ODIN_MODE_HOLD) {
        *roll = chase_clamp_us(p->bias_roll_us + roll_add);
        *pitch = chase_clamp_us(p->bias_pitch_us + pitch_add);
        *yaw = chase_clamp_us(p->bias_yaw_us + yaw_add);
        *thr = chase_clamp_us(p->hover_thrust_us);
        return;
    }

    /* FOLLOW (additions may be zero) */
    *roll = chase_clamp_us(p->bias_roll_us + roll_add);
    *pitch = chase_clamp_us(p->bias_pitch_us + pitch_add);
    *yaw = chase_clamp_us(p->bias_yaw_us + yaw_add);
    *thr = chase_clamp_us(p->hover_thrust_us + thr_add);
}

uint16_t chase_slew_axis(uint16_t cur, uint16_t target, uint32_t slew_us_s, int32_t *rem)
{
    if (slew_us_s == 0) {
        return target;
    }
    if (!rem) {
        return target;
    }
    if (cur == target) {
        return cur;
    }

    *rem += (int32_t)slew_us_s;
    int32_t delta = *rem / CRSF_TASK_HZ;
    *rem %= CRSF_TASK_HZ;
    if (delta <= 0) {
        return cur;
    }

    if (target > cur) {
        int32_t step = (int32_t)target - (int32_t)cur;
        if (step > delta) {
            return (uint16_t)((int32_t)cur + delta);
        }
        return target;
    }

    int32_t step = (int32_t)cur - (int32_t)target;
    if (step > delta) {
        return (uint16_t)((int32_t)cur - delta);
    }
    return target;
}

static uint16_t clamp_u16(uint16_t v, uint16_t lo, uint16_t hi)
{
    if (v < lo) {
        return lo;
    }
    if (v > hi) {
        return hi;
    }
    return v;
}

void chase_hard_limit(uint16_t *roll, uint16_t *pitch, uint16_t *yaw, uint16_t *thr)
{
    if (roll) {
        *roll = clamp_u16(*roll, HARD_ROLL_MIN_US, HARD_ROLL_MAX_US);
    }
    if (pitch) {
        *pitch = clamp_u16(*pitch, HARD_PITCH_MIN_US, HARD_PITCH_MAX_US);
    }
    if (yaw) {
        *yaw = clamp_u16(*yaw, HARD_YAW_MIN_US, HARD_YAW_MAX_US);
    }
    if (thr && *thr > HARD_THR_MAX_US) {
        *thr = HARD_THR_MAX_US;
    }
}

uint16_t chase_apply_ceiling(uint16_t thr, const chase_params_t *p, int32_t agl_mm)
{
    if (!p || p->agl_ceiling_mm <= 0 || agl_mm < 0) {
        return thr;
    }
    if (agl_mm < p->agl_ceiling_mm) {
        return thr;
    }
    uint16_t cap = chase_clamp_us(p->hover_thrust_us);
    return thr > cap ? cap : thr;
}

uint16_t chase_lpf_axis(float *state, int *valid, uint16_t target, int tau_ms)
{
    if (!state || !valid || tau_ms <= 0) {
        return target;
    }
    const float dt = 1000.0f / (float)CRSF_TASK_HZ;
    if (!*valid) {
        *state = (float)target;
        *valid = 1;
        return target;
    }
    float alpha = dt / ((float)tau_ms + dt);
    *state += ((float)target - *state) * alpha;
    return chase_clamp_us((int)(*state + 0.5f));
}

void chase_apply_disarm_outputs(uint16_t *thr, uint16_t *aux1, uint16_t *aux3)
{
    if (thr) {
        *thr = 1000;
    }
    if (aux1) {
        *aux1 = 1000;
    }
    if (aux3) {
        *aux3 = 1000;
    }
}

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
                      uint32_t now_ms)
{
    if (!p || !slew || !roll || !pitch || !yaw || !thr || !aux1 || !aux2 || !aux3) {
        return;
    }

    tag_state_t fresh;
    const tag_state_t *use = tag;
    if (tag && tag->seen && tag->last_ms != 0 && (now_ms - tag->last_ms) > TAG_STALE_MS) {
        fresh = *tag;
        fresh.seen = 0;
        use = &fresh;
    }

    chase_hold_step(hold, mode, now_ms, use);

    uint16_t roll_t;
    uint16_t pitch_t;
    uint16_t yaw_t;
    uint16_t thr_t;
    chase_desired_sticks(mode, p, use, hold, now_ms, &roll_t, &pitch_t, &yaw_t, &thr_t);

    /* Camera-driven modes: low-pass the target so 15 Hz centroid jitter and the
     * 160 ms vision latency do not turn into stick chatter. Other modes: reseed. */
    if (mode == ODIN_MODE_CHASE || mode == ODIN_MODE_HOLD) {
        int v1 = slew->lpf_valid;
        int v2 = slew->lpf_valid;
        int v3 = slew->lpf_valid;
        int v4 = slew->lpf_valid;
        roll_t = chase_lpf_axis(&slew->roll_f, &v1, roll_t, p->lpf_ms);
        pitch_t = chase_lpf_axis(&slew->pitch_f, &v2, pitch_t, p->lpf_ms);
        yaw_t = chase_lpf_axis(&slew->yaw_f, &v3, yaw_t, p->lpf_ms);
        thr_t = chase_lpf_axis(&slew->thr_f, &v4, thr_t, p->lpf_ms);
        slew->lpf_valid = 1;
    } else {
        slew->lpf_valid = 0;
    }


    if (mode == ODIN_MODE_DISARMED) {
        *aux1 = 1000;
        *aux3 = 1000;
    } else {
        *aux1 = 2000;
        *aux3 = 2000;
    }
    *aux2 = 1000;

    if (disarm_snap) {
        chase_apply_disarm_outputs(thr, aux1, aux3);
    }

    *roll = chase_slew_axis(*roll, roll_t, (uint32_t)p->roll_slew_us_s, &slew->roll_rem);
    *pitch = chase_slew_axis(*pitch, pitch_t, (uint32_t)p->pitch_slew_us_s, &slew->pitch_rem);
    *yaw = chase_slew_axis(*yaw, yaw_t, (uint32_t)p->yaw_slew_us_s, &slew->yaw_rem);

    if (disarm_snap) {
        slew->action_us = 0;
        slew->action_rem = 0;
        slew->lpf_valid = 0;
        chase_hard_limit(roll, pitch, yaw, NULL);
        return;
    }

    {
        uint32_t thr_slew = (uint32_t)p->thrust_slew_us_s;
        if (mode == ODIN_MODE_HOVER || mode == ODIN_MODE_HOLD) {
            thr_slew = (uint32_t)p->hover_slew_us_s;
        } else if (mode == ODIN_MODE_LAND) {
            thr_slew = (uint32_t)p->land_slew_us_s;
        }
        *thr = chase_slew_axis(*thr, thr_t, thr_slew, &slew->thr_rem);
    }

    {
        uint16_t action_target = 0;
        if (chase_tilt_commanded(mode, p, use, hold, now_ms) && p->action_thrust_us > 0) {
            /* This is an addition in microseconds, not a stick. Do not pass it through
             * chase_clamp_us: that turned 20 into a target of 1000 and the throttle
             * climbed 20 us every tick. Cap the extra at 200 us. */
            int extra = p->action_thrust_us > 200 ? 200 : p->action_thrust_us;
            action_target = (uint16_t)extra;
        }
        slew->action_us = chase_slew_axis(
            slew->action_us,
            action_target,
            (uint32_t)(p->action_slew_us_s > 0 ? p->action_slew_us_s : 0),
            &slew->action_rem);
        *thr = chase_clamp_us((int)*thr + (int)slew->action_us);
    }

    chase_hard_limit(roll, pitch, yaw, thr);
}

const char *odin_mode_str(odin_mode_t m)
{
    switch (m) {
    case ODIN_MODE_DISARMED:
        return "DISARMED";
    case ODIN_MODE_HOVER:
        return "HOVER";
    case ODIN_MODE_CHASE:
        return "FOLLOW";
    case ODIN_MODE_HOLD:
        return "HOLD";
    case ODIN_MODE_LAND:
        return "LAND";
    default:
        return "DISARMED";
    }
}
