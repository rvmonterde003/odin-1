/* Copy wifi_secrets.example.h to wifi_secrets.h and fill in the hotspot. Do not commit wifi_secrets.h. */

#include "wifi_link.h"
#include "wifi_secrets.h"
#include "cmd_parser.h"
#include "flight_state.h"
#include "chase.h"
#include "pinout.h"

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#include "lwip/sockets.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static const char *TAG = "wifi_link";

#define ODIN_TCP_PORT        8771
#define WIFI_CONNECTED_BIT   BIT0

static EventGroupHandle_t s_wifi_events;
static int s_listen_fd = -1;
static int s_client_fd = -1;

static void close_client(void)
{
    if (s_client_fd >= 0) {
        close(s_client_fd);
        s_client_fd = -1;
    }
}

static int open_listener(void)
{
    int fd = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
    if (fd < 0) {
        ESP_LOGE(TAG, "socket: %d", errno);
        return -1;
    }
    int on = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on));

    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_addr.s_addr = htonl(INADDR_ANY),
        .sin_port = htons(ODIN_TCP_PORT),
    };
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        ESP_LOGE(TAG, "bind: %d", errno);
        close(fd);
        return -1;
    }
    if (listen(fd, 1) != 0) {
        ESP_LOGE(TAG, "listen: %d", errno);
        close(fd);
        return -1;
    }
    int flags = fcntl(fd, F_GETFL, 0);
    fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    return fd;
}

static void accept_client_if_pending(void)
{
    if (s_listen_fd < 0) {
        return;
    }
    struct sockaddr_in peer;
    socklen_t peer_len = sizeof(peer);
    int new_fd = accept(s_listen_fd, (struct sockaddr *)&peer, &peer_len);
    if (new_fd < 0) {
        if (errno != EAGAIN && errno != EWOULDBLOCK) {
            ESP_LOGW(TAG, "accept: %d", errno);
        }
        return;
    }
    close_client();
    s_client_fd = new_fd;
    int nodelay = 1;
    setsockopt(s_client_fd, IPPROTO_TCP, TCP_NODELAY, &nodelay, sizeof(nodelay));
    struct timeval rcv_to = {.tv_sec = 0, .tv_usec = 20000};
    setsockopt(s_client_fd, SOL_SOCKET, SO_RCVTIMEO, &rcv_to, sizeof(rcv_to));
}

static void tcp_write_line(int fd, const char *line)
{
    if (fd < 0 || !line || !line[0]) {
        return;
    }
    send(fd, line, strlen(line), 0);
    send(fd, "\n", 1, 0);
}

static void process_rx_bytes(const uint8_t *data, int n, char *line, size_t *line_len,
                             char *reply, size_t reply_len)
{
    for (int i = 0; i < n; i++) {
        char c = (char)data[i];
        if (c == '\r') {
            continue;
        }
        if (c == '\n') {
            line[*line_len] = '\0';
            if (*line_len > 0) {
                cmd_parse_line(line, reply, reply_len);
                if (reply[0]) {
                    tcp_write_line(s_client_fd, reply);
                }
            }
            *line_len = 0;
        } else if (*line_len + 1 < 160) {
            line[*line_len++] = c;
        } else {
            *line_len = 0;
        }
    }
}

static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id,
                               void *event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        ESP_LOGI(TAG, "got ip: " IPSTR, IP2STR(&event->ip_info.ip));
        if (s_listen_fd < 0) {
            s_listen_fd = open_listener();
            if (s_listen_fd >= 0) {
                ESP_LOGI(TAG, "listening on tcp %d", ODIN_TCP_PORT);
            }
        }
        xEventGroupSetBits(s_wifi_events, WIFI_CONNECTED_BIT);
    }
}

static esp_err_t wifi_init_sta(void)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    s_wifi_events = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                        &wifi_event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                        &wifi_event_handler, NULL, NULL));

    wifi_config_t wcfg = {0};
    strncpy((char *)wcfg.sta.ssid, ODIN_WIFI_SSID, sizeof(wcfg.sta.ssid) - 1);
    strncpy((char *)wcfg.sta.password, ODIN_WIFI_PASS, sizeof(wcfg.sta.password) - 1);
    wcfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wcfg));
    ESP_ERROR_CHECK(esp_wifi_start());

    return ESP_OK;
}

static void wifi_link_task(void *arg)
{
    (void)arg;
    ESP_ERROR_CHECK(wifi_init_sta());

    char line[160];
    size_t line_len = 0;
    char reply[32];
    TickType_t last_telem = xTaskGetTickCount();
    const TickType_t telem_period = pdMS_TO_TICKS(1000 / TELEMETRY_HZ);

    for (;;) {
        accept_client_if_pending();

        if (s_client_fd >= 0) {
            uint8_t buf[128];
            int n = recv(s_client_fd, buf, sizeof(buf), 0);
            if (n > 0) {
                flight_state_lock();
                flight_state_ptr()->last_pi_ms = flight_now_ms();
                flight_state_unlock();
                process_rx_bytes(buf, n, line, &line_len, reply, sizeof(reply));
            } else if (n == 0) {
                close_client();
                line_len = 0;
            }
        }

        TickType_t now = xTaskGetTickCount();
        if (s_client_fd >= 0 && (now - last_telem) >= telem_period) {
            last_telem = now;
            flight_state_lock();
            flight_state_t *s = flight_state_ptr();
            char telem[96];
            int arm = (s->aux1 >= 1500) ? 1 : 0;
            int len = snprintf(telem, sizeof(telem), "STATE %s %d %u %u %u %u %ld\n",
                                odin_mode_str(s->mode),
                                arm,
                                (unsigned)s->roll,
                                (unsigned)s->pitch,
                                (unsigned)s->throttle,
                                (unsigned)s->yaw,
                                (long)s->agl_mm);
            flight_state_unlock();
            if (len > 0) {
                send(s_client_fd, telem, (size_t)len, 0);
            }
        }

        vTaskDelay(pdMS_TO_TICKS(1));
    }
}

void wifi_link_start(void)
{
    if (ODIN_WIFI_SSID[0] == '\0' || ODIN_WIFI_PASS[0] == '\0') {
        ESP_LOGE(TAG, "wifi not configured");
        return;
    }
    xTaskCreatePinnedToCore(wifi_link_task, "wifi_link", 8192, NULL, 5, NULL, 0);
}
