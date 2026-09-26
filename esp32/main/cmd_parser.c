#include "cmd_parser.h"
#include "flight_state.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int parse_mode_word(const char **pp, char *out, size_t out_len)
{
    const char *p = *pp;
    while (*p == ' ') {
        p++;
    }
    size_t i = 0;
    while (*p && *p != ' ' && *p != '\0') {
        if (i + 1 >= out_len) {
            return 0;
        }
        out[i++] = *p++;
    }
    out[i] = '\0';
    if (i == 0) {
        return 0;
    }
    *pp = p;
    return 1;
}

static int parse_int_field(const char **pp, int *out)
{
    const char *p = *pp;
    while (*p == ' ') {
        p++;
    }
    if (*p == '\0') {
        return 0;
    }
    char *end = NULL;
    long v = strtol(p, &end, 10);
    if (end == p) {
        return 0;
    }
    *out = (int)v;
    *pp = end;
    return 1;
}

void cmd_parse_line(const char *line, char *reply, size_t reply_len)
{
    if (reply_len > 0) {
        reply[0] = '\0';
    }
    if (!line || !line[0]) {
        return;
    }

    char buf[160];
    strncpy(buf, line, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    char *p = buf;
    while (*p && isspace((unsigned char)*p)) {
        p++;
    }
    if (!*p) {
        return;
    }

    if (strcmp(p, "PING") == 0) {
        flight_state_lock();
        flight_state_ptr()->last_pi_ms = flight_now_ms();
        flight_state_unlock();
        snprintf(reply, reply_len, "PONG");
        return;
    }

    flight_state_lock();
    flight_state_t *s = flight_state_ptr();
    s->last_pi_ms = flight_now_ms();

    if (strncmp(p, "BIAS ", 5) == 0) {
        const char *q = p + 5;
        int v[4];
        for (int i = 0; i < 4; i++) {
            if (!parse_int_field(&q, &v[i])) {
                flight_state_unlock();
                return;
            }
        }
        s->chase.bias_roll_us = v[0];
        s->chase.bias_pitch_us = v[1];
        s->chase.bias_yaw_us = v[2];
        s->chase.bias_thrust_us = v[3];
    } else if (strncmp(p, "CHASE ", 6) == 0) {
        const char *q = p + 6;
        int v[9];
        for (int i = 0; i < 9; i++) {
            if (!parse_int_field(&q, &v[i])) {
                flight_state_unlock();
                return;
            }
        }
        s->chase.yaw_max_us = v[0];
        s->chase.roll_max_us = v[1];
        s->chase.pitch_min_us = v[2];
        s->chase.pitch_max_us = v[3];
        s->chase.thrust_target_us = v[4];
        s->chase.yaw_slew_us_s = v[5];
        s->chase.roll_slew_us_s = v[6];
        s->chase.pitch_slew_us_s = v[7];
        s->chase.thrust_slew_us_s = v[8];
    } else if (strncmp(p, "HTHR ", 5) == 0) {
        const char *q = p + 5;
        int v[6];
        for (int i = 0; i < 6; i++) {
            if (!parse_int_field(&q, &v[i])) {
                flight_state_unlock();
                return;
            }
        }
        s->chase.hover_thrust_us = v[0];
        s->chase.hover_slew_us_s = v[1];
        s->chase.land_thrust_us = v[2];
        s->chase.land_slew_us_s = v[3];
        s->chase.action_thrust_us = v[4];
        s->chase.action_slew_us_s = v[5];
    } else if (strncmp(p, "SAFE ", 5) == 0) {
        const char *q = p + 5;
        int v[4];
        for (int i = 0; i < 4; i++) {
            if (!parse_int_field(&q, &v[i])) {
                flight_state_unlock();
                return;
            }
        }
        s->chase.area_stop_px2 = v[0] < 0 ? 0 : v[0];
        s->chase.deadband_pct = v[1] < 0 ? 0 : (v[1] > 50 ? 50 : v[1]);
        s->chase.lpf_ms = v[2] < 0 ? 0 : v[2];
        s->chase.agl_ceiling_mm = v[3] < 0 ? 0 : v[3];
    } else if (strncmp(p, "PILOT ", 6) == 0) {
        const char *q = p + 6;
        char mode_word[16];
        int cx;
        int cy;
        int area;
        if (!parse_mode_word(&q, mode_word, sizeof(mode_word)) ||
            !parse_int_field(&q, &cx) || !parse_int_field(&q, &cy) ||
            !parse_int_field(&q, &area)) {
            flight_state_unlock();
            return;
        }
        s->tag.cx = cx;
        s->tag.cy = cy;
        s->tag.area = area;
        s->tag.w = 320;
        s->tag.h = 320;
        s->tag.seen = (cx != 0 || cy != 0 || area != 0) ? 1 : 0;
        s->tag.last_ms = flight_now_ms();
        if (strcmp(mode_word, "DISARM") == 0) {
            s->mode = ODIN_MODE_DISARMED;
        } else if (strcmp(mode_word, "HOVER") == 0) {
            /* A PILOT line never arms. The Pi repeats PILOT <mode> on every detect
             * pass, so arming here would arm on any Pi restart. Only CMD HOVER arms. */
            if (s->mode != ODIN_MODE_DISARMED) {
                s->mode = ODIN_MODE_HOVER;
            }
        } else if (strcmp(mode_word, "FOLLOW") == 0) {
            if (s->mode != ODIN_MODE_DISARMED) {
                s->mode = ODIN_MODE_CHASE;
            }
        } else if (strcmp(mode_word, "HOLD") == 0) {
            if (s->mode != ODIN_MODE_DISARMED) {
                s->mode = ODIN_MODE_HOLD;
            }
        } else if (strcmp(mode_word, "LAND") == 0) {
            if (s->mode != ODIN_MODE_DISARMED) {
                s->mode = ODIN_MODE_LAND;
            }
        }
    } else if (strcmp(p, "CMD HOVER") == 0) {
        s->mode = ODIN_MODE_HOVER;
    } else if (strcmp(p, "CMD CHASE") == 0 || strcmp(p, "CMD FOLLOW") == 0) {
        if (s->mode != ODIN_MODE_DISARMED) {
            s->mode = ODIN_MODE_CHASE;
        }
    } else if (strcmp(p, "CMD LAND") == 0) {
        if (s->mode != ODIN_MODE_DISARMED) {
            s->mode = ODIN_MODE_LAND;
        }
    } else if (strcmp(p, "CMD DISARM") == 0) {
        s->mode = ODIN_MODE_DISARMED;
    } else if (strncmp(p, "TAG ", 4) == 0) {
        const char *q = p + 4;
        int v[5];
        for (int i = 0; i < 5; i++) {
            if (!parse_int_field(&q, &v[i])) {
                flight_state_unlock();
                return;
            }
        }
        s->tag.seen = v[0] ? 1 : 0;
        s->tag.cx = v[1];
        s->tag.cy = v[2];
        s->tag.w = v[3];
        s->tag.h = v[4];
        s->tag.last_ms = flight_now_ms();
    }
    /* Unknown lines ignored */

    flight_state_unlock();
}
