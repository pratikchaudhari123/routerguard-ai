#include <math.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

#include "nvs_flash.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "esp_http_client.h"
#include "esp_timer.h"
#include "esp_mac.h"
#include "lwip/inet.h"
#include "lwip/ip4_addr.h"
#include "ping/ping_sock.h"

#include "sdkconfig.h"

#define TAG "routerguard_csi"
#define MAX_SUBCARRIERS 128
#define CSI_QUEUE_DEPTH 16
#define CSI_POST_INTERVAL_MS 100

#ifndef CONFIG_WIFISENSE_WIFI_SSID
#define CONFIG_WIFISENSE_WIFI_SSID ""
#endif
#ifndef CONFIG_WIFISENSE_WIFI_PASSWORD
#define CONFIG_WIFISENSE_WIFI_PASSWORD ""
#endif
#ifndef CONFIG_WIFISENSE_API_URL
#define CONFIG_WIFISENSE_API_URL "http://192.168.31.131:8000/api/csi"
#endif
#ifndef CONFIG_WIFISENSE_DEVICE_ID
#define CONFIG_WIFISENSE_DEVICE_ID "esp32-s3-csi-01"
#endif

typedef struct {
    int count;
    int rssi;
    float amplitudes[MAX_SUBCARRIERS];
} csi_packet_t;

static QueueHandle_t s_csi_queue;
static uint8_t s_ap_bssid[6];
static bool s_csi_ready;

static void post_csi_task(void *arg)
{
    csi_packet_t packet;
    char body[4096];

    esp_http_client_config_t cfg = {
        .url = CONFIG_WIFISENSE_API_URL,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 3000,
    };

    while (true) {
        if (xQueueReceive(s_csi_queue, &packet, portMAX_DELAY) != pdTRUE) {
            continue;
        }

        int used = snprintf(body, sizeof(body),
            "{\"device_id\":\"%s\",\"rssi\":%d,\"amplitudes\":[",
            CONFIG_WIFISENSE_DEVICE_ID, packet.rssi);

        for (int i = 0; i < packet.count && used > 0 && used < (int)sizeof(body); i++) {
            int n = snprintf(body + used, sizeof(body) - used,
                "%s%.2f", i ? "," : "", packet.amplitudes[i]);
            if (n < 0 || n >= (int)(sizeof(body) - used)) {
                used = -1;
                break;
            }
            used += n;
        }

        if (used < 0 || used + 3 >= (int)sizeof(body)) {
            ESP_LOGW(TAG, "CSI vector too large; dropping packet");
            continue;
        }
        snprintf(body + used, sizeof(body) - used, "]}");

        esp_http_client_handle_t client = esp_http_client_init(&cfg);
        if (!client) {
            ESP_LOGE(TAG, "Could not create HTTP client");
            continue;
        }
        esp_http_client_set_header(client, "Content-Type", "application/json");
        esp_http_client_set_post_field(client, body, (int)strlen(body));
        esp_err_t err = esp_http_client_perform(client);
        int status = esp_http_client_get_status_code(client);
        if (err == ESP_OK && status >= 200 && status < 300) {
            ESP_LOGI(TAG, "Posted %d real CSI subcarriers to RouterGuard (HTTP %d)",
                     packet.count, status);
        } else {
            ESP_LOGW(TAG, "CSI POST failed: %s, HTTP %d",
                     esp_err_to_name(err), status);
        }
        esp_http_client_cleanup(client);
        vTaskDelay(pdMS_TO_TICKS(CSI_POST_INTERVAL_MS));
    }
}

static void wifi_csi_rx_cb(void *ctx, wifi_csi_info_t *info)
{
    if (!info || !info->buf || !s_csi_ready) return;

    // Only use CSI from the connected access point, not unrelated nearby transmitters.
    if (memcmp(info->mac, s_ap_bssid, sizeof(s_ap_bssid)) != 0) return;

    // ESP32-S3 CSI samples are interleaved signed I/Q bytes.
    // Convert each complex pair to magnitude. The raw vector is measured from
    // the radio callback; no synthetic or RSSI-derived values are inserted.
    csi_packet_t packet = {0};
    packet.rssi = info->rx_ctrl.rssi;
    int pairs = info->len / 2;
    if (pairs > MAX_SUBCARRIERS) pairs = MAX_SUBCARRIERS;

    for (int i = 0; i < pairs; i++) {
        float real = (float)((int8_t)info->buf[i * 2]);
        float imag = (float)((int8_t)info->buf[i * 2 + 1]);
        packet.amplitudes[i] = sqrtf(real * real + imag * imag);
    }
    packet.count = pairs;

    if (packet.count >= 8) {
        // Non-blocking: keep the Wi-Fi callback short.
        xQueueSend(s_csi_queue, &packet, 0);
    }
}

static void start_csi_and_ping_router(void)
{
    wifi_ap_record_t ap = {0};
    ESP_ERROR_CHECK(esp_wifi_sta_get_ap_info(&ap));
    memcpy(s_ap_bssid, ap.bssid, sizeof(s_ap_bssid));

    wifi_csi_config_t csi_config = {
        .lltf_en = true,
        .htltf_en = false,
        .stbc_htltf2_en = false,
        .ltf_merge_en = true,
        .channel_filter_en = true,
        .manu_scale = true,
        .shift = true,
    };

    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_config));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(wifi_csi_rx_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
    s_csi_ready = true;

    esp_netif_ip_info_t ip_info = {0};
    esp_netif_t *sta = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (!sta || esp_netif_get_ip_info(sta, &ip_info) != ESP_OK) {
        ESP_LOGE(TAG, "Could not read Wi-Fi gateway address");
        return;
    }

    ESP_LOGI(TAG, "Connected. Gateway: " IPSTR, IP2STR(&ip_info.gw));
    ESP_LOGI(TAG, "Sending real CSI to %s", CONFIG_WIFISENSE_API_URL);

    esp_ping_config_t ping_cfg = ESP_PING_DEFAULT_CONFIG();
    ping_cfg.count = 0;
    ping_cfg.interval_ms = 100;
    ping_cfg.data_size = 1;
    ping_cfg.target_addr.type = ESP_IPADDR_TYPE_V4;
    ping_cfg.target_addr.u_addr.ip4.addr = ip_info.gw.addr;

    esp_ping_callbacks_t callbacks = {0};
    esp_ping_handle_t ping = NULL;
    ESP_ERROR_CHECK(esp_ping_new_session(&ping_cfg, &callbacks, &ping));
    ESP_ERROR_CHECK(esp_ping_start(ping));
}

static void wifi_event_handler(void *arg, esp_event_base_t base,
                               int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        s_csi_ready = false;
        ESP_LOGW(TAG, "Wi-Fi disconnected; reconnecting");
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ESP_LOGI(TAG, "Wi-Fi connected; preparing CSI capture");
        start_csi_and_ping_router();
    }
}

void app_main(void)
{
    if (strlen(CONFIG_WIFISENSE_WIFI_SSID) == 0) {
        ESP_LOGE(TAG, "Set Wi-Fi SSID in idf.py menuconfig first");
        return;
    }

    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    s_csi_queue = xQueueCreate(CSI_QUEUE_DEPTH, sizeof(csi_packet_t));
    if (!s_csi_queue) {
        ESP_LOGE(TAG, "Could not create CSI queue");
        return;
    }
    xTaskCreate(post_csi_task, "csi_http_post", 6144, NULL, 5, NULL);

    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_cfg));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                &wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                &wifi_event_handler, NULL));

    wifi_config_t wifi_cfg = {0};
    strlcpy((char *)wifi_cfg.sta.ssid, CONFIG_WIFISENSE_WIFI_SSID,
            sizeof(wifi_cfg.sta.ssid));
    strlcpy((char *)wifi_cfg.sta.password, CONFIG_WIFISENSE_WIFI_PASSWORD,
            sizeof(wifi_cfg.sta.password));
    wifi_cfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());
}
