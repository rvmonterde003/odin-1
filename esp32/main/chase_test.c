#include "chase.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int expect_sticks(odin_mode_t mode,
                         const chase_params_t *p,
                         const tag_state_t *tag,
                         hold_state_t *hold,
                         uint32_t now_ms,
                         uint16_t er,
                         uint16_t ep,
                         uint16_t ey,
                         uint16_t et,
                         const char *label)
{
    uint16_t r;
    uint16_t pit;
    uint16_t y;
    uint16_t t;
    chase_desired_sticks(mode, p, tag, hold, now_ms, &r, &pit, &y, &t);
    if (r != er || pit != ep || y != ey || t != et) {
        fprintf(stderr, "FAIL %s: got r=%u p=%u y=%u t=%u want r=%u p=%u y=%u t=%u\n",
                label, (unsigned)r, (unsigned)pit, (unsigned)y, (unsigned)t,
                (unsigned)er, (unsigned)ep, (unsigned)ey, (unsigned)et);
        return 1;
    }
    return 0;
}

static int expect_hold_pitch(const chase_params_t *p,
                             tag_state_t *tag,
                             hold_state_t *hold,
                             uint32_t now_ms,
                             uint16_t ep,
                             const char *label)
{
    chase_hold_step(hold, ODIN_MODE_HOLD, now_ms, tag);
    return expect_sticks(ODIN_MODE_HOLD, p, tag, hold, now_ms,
                         1500, ep, 1500, 1350, label);
}

static int test_disarm_outputs(void)
{
    chase_params_t p;
    tag_state_t tag = {.seen = 1, .cx = 160, .cy = 160, .w = 320, .h = 320};
    hold_state_t hold;
    slew_state_t slew;
    chase_params_set_defaults(&p);
    hold_state_init(&hold);
    slew_state_init(&slew);

    uint16_t roll = 1530;
    uint16_t pitch = 1620;
    uint16_t yaw = 1580;
    uint16_t thr = 1390;
    uint16_t aux1 = 2000;
    uint16_t aux2 = 1000;
    uint16_t aux3 = 2000;

    chase_stick_tick(ODIN_MODE_DISARMED, &p, &tag, &hold, &slew, true,
                     &roll, &pitch, &yaw, &thr, &aux1, &aux2, &aux3, 0);

    if (thr != 1000 || aux1 != 1000 || aux3 != 1000) {
        fprintf(stderr, "FAIL disarm snap: thr=%u aux1=%u aux3=%u\n",
                (unsigned)thr, (unsigned)aux1, (unsigned)aux3);
        return 1;
    }
    return 0;
}

static int test_stale_tag(void)
{
    chase_params_t p;
    tag_state_t tag;
    hold_state_t hold;
    slew_state_t slew;
    chase_params_set_defaults(&p);
    hold_state_init(&hold);
    slew_state_init(&slew);
    p.pitch_slew_us_s = 0;
    p.lpf_ms = 0;
    tag.seen = 1;
    tag.cx = 160;
    tag.cy = 160;
    tag.w = 320;
    tag.h = 320;
    tag.last_ms = 1000;

    uint16_t roll = 1500;
    uint16_t pitch = 1500;
    uint16_t yaw = 1500;
    uint16_t thr = 1350;
    uint16_t aux1 = 2000;
    uint16_t aux2 = 1000;
    uint16_t aux3 = 2000;

    chase_stick_tick(ODIN_MODE_CHASE, &p, &tag, &hold, &slew, false,
                     &roll, &pitch, &yaw, &thr, &aux1, &aux2, &aux3, 1400);
    if (pitch != 1500) {
        fprintf(stderr, "FAIL stale tag still pitching: pitch=%u\n", (unsigned)pitch);
        return 1;
    }

    chase_stick_tick(ODIN_MODE_CHASE, &p, &tag, &hold, &slew, false,
                     &roll, &pitch, &yaw, &thr, &aux1, &aux2, &aux3, 1200);
    if (pitch != 1620) {
        fprintf(stderr, "FAIL fresh tag pitch: pitch=%u\n", (unsigned)pitch);
        return 1;
    }
    return 0;
}

static int test_slew_fraction(void)
{
    uint16_t cur = 1350;
    int32_t rem = 0;
    int count2 = 0;
    int count3 = 0;

    for (int i = 0; i < 20; i++) {
        uint16_t prev = cur;
        cur = chase_slew_axis(cur, 1400, 250, &rem);
        int delta = (int)cur - (int)prev;
        if (delta == 2) {
            count2++;
        } else if (delta == 3) {
            count3++;
        } else if (delta == 0 && cur == 1400) {
            break;
        }
    }
    if (count2 < 1 || count3 < 1) {
        fprintf(stderr, "FAIL slew fraction: count2=%d count3=%d\n", count2, count3);
        return 1;
    }
    return 0;
}

static int test_hold_cases(void)
{
    chase_params_t p;
    tag_state_t tag;
    hold_state_t hold;
    int err = 0;

    chase_params_set_defaults(&p);
    hold_state_init(&hold);
    tag.w = 320;
    tag.h = 320;
    tag.seen = 1;
    tag.cx = 160;
    tag.cy = 160;

    tag.area = 2000;
    chase_hold_step(&hold, ODIN_MODE_HOLD, 0, &tag);
    err |= expect_hold_pitch(&p, &tag, &hold, 1000, 1500, "hold 1.0s area 2000");

    tag.area = 1000;
    chase_hold_step(&hold, ODIN_MODE_HOLD, 1600, &tag);
    err |= expect_hold_pitch(&p, &tag, &hold, 1700, 1500, "hold ref area 1000");

    tag.area = 2000;
    err |= expect_hold_pitch(&p, &tag, &hold, 1700, 1380, "hold tag larger");

    tag.area = 500;
    err |= expect_hold_pitch(&p, &tag, &hold, 1700, 1560, "hold tag half size");

    tag.seen = 0;
    tag.area = 0;
    err |= expect_hold_pitch(&p, &tag, &hold, 1700, 1500, "hold tag missing");

    return err;
}
static int test_action_thrust(void)
{
    chase_params_t p;
    tag_state_t tag;
    hold_state_t hold;
    slew_state_t slew;
    uint16_t roll = 1500;
    uint16_t pitch = 1500;
    uint16_t yaw = 1500;
    uint16_t thr = 1560;
    uint16_t aux1 = 2000;
    uint16_t aux2 = 1000;
    uint16_t aux3 = 2000;
    chase_params_set_defaults(&p);
    hold_state_init(&hold);
    slew_state_init(&slew);
    p.hover_thrust_us = 1560;
    p.action_thrust_us = 20;
    p.action_slew_us_s = 2000;
    p.pitch_slew_us_s = 0;
    p.roll_slew_us_s = 0;
    p.yaw_slew_us_s = 0;
    p.thrust_slew_us_s = 0;
    p.hover_slew_us_s = 0;
    p.thrust_target_us = 0;
    p.lpf_ms = 0;
    tag.seen = 1;
    tag.cx = 160;
    tag.cy = 160;
    tag.area = 1000;
    tag.w = 320;
    tag.h = 320;
    tag.last_ms = 1000;
    chase_stick_tick(ODIN_MODE_CHASE, &p, &tag, &hold, &slew, false,
                     &roll, &pitch, &yaw, &thr, &aux1, &aux2, &aux3, 1000);
    if (thr != 1580) {
        fprintf(stderr, "FAIL action on: thr=%u\n", (unsigned)thr);
        return 1;
    }
    chase_stick_tick(ODIN_MODE_CHASE, &p, &tag, &hold, &slew, false,
                     &roll, &pitch, &yaw, &thr, &aux1, &aux2, &aux3, 1010);
    if (thr != 1580) {
        fprintf(stderr, "FAIL action once: thr=%u\n", (unsigned)thr);
        return 1;
    }
    chase_stick_tick(ODIN_MODE_HOVER, &p, &tag, &hold, &slew, false,
                     &roll, &pitch, &yaw, &thr, &aux1, &aux2, &aux3, 1020);
    if (thr != 1560) {
        fprintf(stderr, "FAIL action off in hover: thr=%u\n", (unsigned)thr);
        return 1;
    }
    slew_state_init(&slew);
    thr = 1560;
    p.pitch_max_us = 0;
    p.pitch_min_us = 0;
    p.roll_max_us = 0;
    p.yaw_max_us = 80;
    tag.cx = 320;
    chase_stick_tick(ODIN_MODE_CHASE, &p, &tag, &hold, &slew, false,
                     &roll, &pitch, &yaw, &thr, &aux1, &aux2, &aux3, 1100);
    if (thr != 1560 || yaw == 1500) {
        fprintf(stderr, "FAIL yaw only: thr=%u yaw=%u\n", (unsigned)thr, (unsigned)yaw);
        return 1;
    }
    return 0;
}
static int test_deadband(void)
{
    chase_params_t p;
    tag_state_t tag = {.seen = 1, .cx = 160, .cy = 160, .w = 320, .h = 320, .area = 1000};
    hold_state_t hold;
    int err = 0;
    chase_params_set_defaults(&p);
    hold_state_init(&hold);
    /* 5% right of centre: inside the 10% deadband, yaw and roll stay on bias */
    tag.cx = 168;
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1500, 1614, 1500, 1350, "deadband inside");
    /* frame edge still gives full scale */
    tag.cx = 320;
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1530, 1500, 1580, 1350, "deadband edge");
    /* 5% above centre: thrust stays on hover */
    tag.cx = 160;
    tag.cy = 152;
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1500, 1620, 1500, 1350, "deadband vertical");
    /* deadband 0 restores the plain proportional law */
    p.deadband_pct = 0;
    tag.cx = 168;
    tag.cy = 160;
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1501, 1614, 1504, 1350, "deadband off");
    return err;
}

static int test_standoff(void)
{
    chase_params_t p;
    tag_state_t tag = {.seen = 1, .cx = 160, .cy = 160, .w = 320, .h = 320};
    hold_state_t hold;
    int err = 0;
    chase_params_set_defaults(&p);
    hold_state_init(&hold);
    p.area_stop_px2 = 4000;
    tag.area = 1000;   /* far: 75% of pitch_max */
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1500, 1590, 1500, 1350, "standoff far");
    tag.area = 4000;   /* at the stop: no pitch */
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1500, 1500, 1500, 1350, "standoff at stop");
    tag.area = 8000;   /* past the stop: brake, capped at half pitch_max */
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1500, 1440, 1500, 1350, "standoff brake");
    tag.area = 40000;
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1500, 1440, 1500, 1350, "standoff brake cap");
    p.area_stop_px2 = 0;  /* disabled: spec table value */
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1500, 1620, 1500, 1350, "standoff off");
    return err;
}

static int test_hard_limits(void)
{
    chase_params_t p;
    tag_state_t tag = {.seen = 1, .cx = 320, .cy = 0, .w = 320, .h = 320, .area = 1000, .last_ms = 1000};
    hold_state_t hold;
    slew_state_t slew;
    chase_params_set_defaults(&p);
    hold_state_init(&hold);
    slew_state_init(&slew);
    /* A hostile preset: bias near full stick, huge additions, no slew, no filter */
    p.bias_roll_us = 1900;
    p.bias_pitch_us = 1100;
    p.bias_yaw_us = 1900;
    p.hover_thrust_us = 1900;
    p.yaw_max_us = 500;
    p.roll_max_us = 500;
    p.pitch_max_us = 500;
    p.thrust_target_us = 500;
    p.roll_slew_us_s = 0;
    p.pitch_slew_us_s = 0;
    p.yaw_slew_us_s = 0;
    p.thrust_slew_us_s = 0;
    p.hover_slew_us_s = 0;
    p.lpf_ms = 0;
    p.deadband_pct = 0;
    uint16_t roll = 1500, pitch = 1500, yaw = 1500, thr = 1350;
    uint16_t aux1 = 2000, aux2 = 1000, aux3 = 2000;
    chase_stick_tick(ODIN_MODE_CHASE, &p, &tag, &hold, &slew, false,
                     &roll, &pitch, &yaw, &thr, &aux1, &aux2, &aux3, 1000);
    /* tag at the right edge: pitch fade gives 0 addition, so pitch is the low bias, clamped up */
    if (roll != HARD_ROLL_MAX_US || pitch != HARD_PITCH_MIN_US || yaw != HARD_YAW_MAX_US || thr != HARD_THR_MAX_US) {
        fprintf(stderr, "FAIL hard limits: r=%u p=%u y=%u t=%u\n",
                (unsigned)roll, (unsigned)pitch, (unsigned)yaw, (unsigned)thr);
        return 1;
    }
    /* Hover with an over-range hover thrust is still capped */
    thr = 1350;
    chase_stick_tick(ODIN_MODE_HOVER, &p, &tag, &hold, &slew, false,
                     &roll, &pitch, &yaw, &thr, &aux1, &aux2, &aux3, 1010);
    if (thr != HARD_THR_MAX_US) {
        fprintf(stderr, "FAIL hover thr cap: t=%u\n", (unsigned)thr);
        return 1;
    }
    /* Disarm snap still wins over everything */
    chase_stick_tick(ODIN_MODE_DISARMED, &p, &tag, &hold, &slew, true,
                     &roll, &pitch, &yaw, &thr, &aux1, &aux2, &aux3, 1020);
    if (thr != 1000 || aux1 != 1000) {
        fprintf(stderr, "FAIL disarm after limits: t=%u aux1=%u\n", (unsigned)thr, (unsigned)aux1);
        return 1;
    }
    return 0;
}

static int test_lpf(void)
{
    chase_params_t p;
    tag_state_t tag = {.seen = 1, .cx = 320, .cy = 160, .w = 320, .h = 320, .area = 1000, .last_ms = 1000};
    hold_state_t hold;
    slew_state_t slew;
    chase_params_set_defaults(&p);
    hold_state_init(&hold);
    slew_state_init(&slew);
    p.yaw_slew_us_s = 0;
    p.lpf_ms = 150;
    uint16_t roll = 1500, pitch = 1500, yaw = 1500, thr = 1350;
    uint16_t aux1 = 2000, aux2 = 1000, aux3 = 2000;
    /* Seed tick: enter FOLLOW from HOVER with the tag already at the right edge.
     * The filter seeds on the first target, so the first tick jumps to it. */
    chase_stick_tick(ODIN_MODE_HOVER, &p, &tag, &hold, &slew, false,
                     &roll, &pitch, &yaw, &thr, &aux1, &aux2, &aux3, 1000);
    tag.cx = 160;
    chase_stick_tick(ODIN_MODE_CHASE, &p, &tag, &hold, &slew, false,
                     &roll, &pitch, &yaw, &thr, &aux1, &aux2, &aux3, 1010);
    if (yaw != 1500) {
        fprintf(stderr, "FAIL lpf seed: yaw=%u\n", (unsigned)yaw);
        return 1;
    }
    /* Tag jumps to the right edge: target 1580. One tick moves ~6% of the way. */
    tag.cx = 320;
    chase_stick_tick(ODIN_MODE_CHASE, &p, &tag, &hold, &slew, false,
                     &roll, &pitch, &yaw, &thr, &aux1, &aux2, &aux3, 1020);
    if (yaw <= 1500 || yaw >= 1520) {
        fprintf(stderr, "FAIL lpf first step: yaw=%u\n", (unsigned)yaw);
        return 1;
    }
    /* After 100 ticks (1 s) it has converged. */
    for (int i = 0; i < 100; i++) {
        tag.last_ms = 1030 + i * 10;  /* keep the tag fresh across the 300 ms stale gate */
        chase_stick_tick(ODIN_MODE_CHASE, &p, &tag, &hold, &slew, false,
                         &roll, &pitch, &yaw, &thr, &aux1, &aux2, &aux3, 1030 + i * 10);
    }
    if (yaw != 1580) {
        fprintf(stderr, "FAIL lpf converge: yaw=%u\n", (unsigned)yaw);
        return 1;
    }
    return 0;
}

static int test_ceiling(void)
{
    chase_params_t p;
    chase_params_set_defaults(&p);
    p.hover_thrust_us = 1350;
    p.agl_ceiling_mm = 1500;
    if (chase_apply_ceiling(1390, &p, -1) != 1390) {
        fprintf(stderr, "FAIL ceiling with no range\n");
        return 1;
    }
    if (chase_apply_ceiling(1390, &p, 1200) != 1390) {
        fprintf(stderr, "FAIL ceiling below\n");
        return 1;
    }
    if (chase_apply_ceiling(1390, &p, 1500) != 1350) {
        fprintf(stderr, "FAIL ceiling at\n");
        return 1;
    }
    if (chase_apply_ceiling(1300, &p, 1800) != 1300) {
        fprintf(stderr, "FAIL ceiling never adds\n");
        return 1;
    }
    p.agl_ceiling_mm = 0;
    if (chase_apply_ceiling(1390, &p, 3000) != 1390) {
        fprintf(stderr, "FAIL ceiling off\n");
        return 1;
    }
    return 0;
}

int main(void)
{
    chase_params_t p;
    tag_state_t tag;
    hold_state_t hold;
    int err = 0;

    chase_params_set_defaults(&p);
    hold_state_init(&hold);
    tag.w = 320;
    tag.h = 320;
    tag.seen = 1;

    tag.cx = 160;
    tag.cy = 160;
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1500, 1620, 1500, 1350, "center");

    tag.cx = 320;
    tag.cy = 160;
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1530, 1500, 1580, 1350, "right");

    tag.cx = 0;
    tag.cy = 160;
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1470, 1500, 1420, 1350, "left");

    tag.cx = 160;
    tag.cy = 0;
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1500, 1620, 1500, 1390, "top");

    tag.cx = 160;
    tag.cy = 320;
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1500, 1620, 1500, 1310, "bottom");

    tag.seen = 0;
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1500, 1500, 1500, 1350, "miss");

    tag.seen = 1;
    tag.cx = 160;
    tag.cy = 160;
    p.hover_thrust_us = 1400;
    p.bias_thrust_us = 1200;
    err |= expect_sticks(ODIN_MODE_CHASE, &p, &tag, &hold, 0, 1500, 1620, 1500, 1400, "chase uses hover thrust");
    err |= expect_sticks(ODIN_MODE_HOVER, &p, &tag, &hold, 0, 1500, 1500, 1500, 1400, "hover");
    p.land_thrust_us = 1100;
    err |= expect_sticks(ODIN_MODE_LAND, &p, &tag, &hold, 0, 1500, 1500, 1500, 1100, "land");

    err |= test_hold_cases();
    err |= test_disarm_outputs();
    err |= test_slew_fraction();
    err |= test_stale_tag();
    err |= test_action_thrust();
    err |= test_deadband();
    err |= test_standoff();
    err |= test_hard_limits();
    err |= test_lpf();
    err |= test_ceiling();

    if (err != 0) {
        return 1;
    }
    printf("chase ok\n");
    return 0;
}

