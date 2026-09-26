#pragma once

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Parse one complete Pi line. Sets reply[0]=0 unless PING (PONG). */
void cmd_parse_line(const char *line, char *reply, size_t reply_len);

#ifdef __cplusplus
}
#endif
