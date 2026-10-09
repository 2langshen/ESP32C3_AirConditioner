/*
 * ESP32-C3  +  IRext offline Konka AC code  +  RMT 38kHz IR
 *           +  WiFi  +  local MQTT broker (plain)
 *
 * MQTT: broker mqtt://192.168.31.32:1883
 *   subscribe  ac/cmd    (JSON or shorthands)
 *   publish    ac/state
 *
 * Local JSON keys:
 *   power  0/1 or true/false
 *   mode   0=cool 1=heat 2=auto 3=fan 4=dry
 *   temp   16..30
 *   fan    0=auto 1=low 2=med 3=high
 *   swing  0/1 or true/false
 * Text shorthands: p(on/off) m + - f w i o a 1..5 c v h
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "esp_chip_info.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "mqtt_client.h"
#include "cJSON.h"

#include "secrets.h"   /* WIFI_SSID, WIFI_PASS, MQTT_URI, MQTT_CLIENT_ID */

#include "driver/rmt_tx.h"
#include "driver/rmt_encoder.h"
#include "driver/uart.h"

#include "ir_decode.h"
#include "ir_ac_control.h"
#include "ir_defs.h"

#include "xiaomi_pats.h"
#include "xiaomi_state_pats.h"
#include "xiaomi_off_pats.h"
#include "xiaomi_model_8101.h"

static const char *TAG = "AC";

/* ================= WiFi (credentials in secrets.h) ================= */
static EventGroupHandle_t s_wifi_evt;
#define WIFI_CONNECTED_BIT BIT0

/* ================= MQTT (local) ================= */
#define TOPIC_CMD       "ac/cmd"
#define TOPIC_STATE     "ac/state"
#define TOPIC_TRY       "ac/try"

static esp_mqtt_client_handle_t s_mqtt = NULL;
static bool s_mqtt_up = false;

/* ================= Embedded Konka AC code ================= */
extern const uint8_t konka_ac_3557_bin_start[] asm("_binary_konka_ac_3557_bin_start");
extern const uint8_t konka_ac_3557_bin_end[]   asm("_binary_konka_ac_3557_bin_end");
extern const uint8_t konka_ac_3558_bin_start[] asm("_binary_konka_ac_3558_bin_start");
extern const uint8_t konka_ac_3558_bin_end[]   asm("_binary_konka_ac_3558_bin_end");
extern const uint8_t konka_ac_3559_bin_start[] asm("_binary_konka_ac_3559_bin_start");
extern const uint8_t konka_ac_3559_bin_end[]   asm("_binary_konka_ac_3559_bin_end");
extern const uint8_t konka_ac_3560_bin_start[] asm("_binary_konka_ac_3560_bin_start");
extern const uint8_t konka_ac_3560_bin_end[]   asm("_binary_konka_ac_3560_bin_end");
extern const uint8_t konka_ac_3561_bin_start[] asm("_binary_konka_ac_3561_bin_start");
extern const uint8_t konka_ac_3561_bin_end[]   asm("_binary_konka_ac_3561_bin_end");

typedef struct { const char *label; const uint8_t *start; const uint8_t *end; } remote_bin_t;
static const remote_bin_t s_remotes[] = {
    { "new_ac_2807 (id 3557)", konka_ac_3557_bin_start, konka_ac_3557_bin_end },
    { "new_ac_5372 (id 3558)", konka_ac_3558_bin_start, konka_ac_3558_bin_end },
    { "new_ac_3657 (id 3559)", konka_ac_3559_bin_start, konka_ac_3559_bin_end },
    { "new_ac_3327 (id 3560)", konka_ac_3560_bin_start, konka_ac_3560_bin_end },
    { "new_ac_3022 (id 3561)", konka_ac_3561_bin_start, konka_ac_3561_bin_end },
};
#define REMOTE_COUNT (sizeof(s_remotes) / sizeof(s_remotes[0]))

/* ================= IR emitter ================= */
#define IR_TX_GPIO       4
#define IR_RESOLUTION_HZ 1000000

static rmt_channel_handle_t s_tx_channel = NULL;
static rmt_encoder_handle_t s_copy_encoder = NULL;
static rmt_symbol_word_t s_symbols[1024];
static int s_carrier_hz = 38000;

static void ir_set_carrier(int hz)
{
    rmt_carrier_config_t carrier = { .duty_cycle = 0.33, .frequency_hz = (uint32_t)hz };
    rmt_disable(s_tx_channel);
    ESP_ERROR_CHECK(rmt_apply_carrier(s_tx_channel, &carrier));
    ESP_ERROR_CHECK(rmt_enable(s_tx_channel));
    s_carrier_hz = hz;
}

static void ir_tx_init(void)
{
    rmt_tx_channel_config_t tx_cfg = {
        .clk_src = RMT_CLK_SRC_DEFAULT, .resolution_hz = IR_RESOLUTION_HZ,
        .mem_block_symbols = 64, .trans_queue_depth = 4, .gpio_num = IR_TX_GPIO,
        .flags.io_od_mode = 0, .flags.with_dma = false,
    };
    ESP_ERROR_CHECK(rmt_new_tx_channel(&tx_cfg, &s_tx_channel));
    rmt_carrier_config_t carrier = { .duty_cycle = 0.33, .frequency_hz = 38000 };
    ESP_ERROR_CHECK(rmt_apply_carrier(s_tx_channel, &carrier));
    ESP_ERROR_CHECK(rmt_enable(s_tx_channel));
    rmt_copy_encoder_config_t enc_cfg = {};
    ESP_ERROR_CHECK(rmt_new_copy_encoder(&enc_cfg, &s_copy_encoder));
    ESP_LOGI(TAG, "IR TX ready on GPIO%d @ 38kHz", IR_TX_GPIO);
}

static void ir_send(const uint16_t *data, int len)
{
    int nsym = 0;
    int half = 0;
    rmt_symbol_word_t cur = { .level0 = 0, .duration0 = 0, .level1 = 0, .duration1 = 0 };
    int maxsym = (int)(sizeof(s_symbols) / sizeof(s_symbols[0]));
    for (int k = 0; k < len; k++) {
        int level = (k % 2 == 0) ? 1 : 0;
        uint32_t dur = data[k];
        while (dur > 0 && nsym < maxsym) {
            uint32_t chunk = dur > 32767 ? 32767 : dur;
            dur -= chunk;
            if (half == 0) {
                cur.level0 = level;
                cur.duration0 = chunk;
                half = 1;
            } else {
                cur.level1 = level;
                cur.duration1 = chunk;
                s_symbols[nsym++] = cur;
                half = 0;
            }
        }
    }
    if (half == 1) {
        cur.level1 = 0;
        cur.duration1 = 1;
        s_symbols[nsym++] = cur;
    }
    if (nsym == 0) return;
    rmt_transmit_config_t tx = { .loop_count = 0 };
    ESP_ERROR_CHECK(rmt_transmit(s_tx_channel, s_copy_encoder, s_symbols,
                                 nsym * sizeof(rmt_symbol_word_t), &tx));
    rmt_tx_wait_all_done(s_tx_channel, portMAX_DELAY);
}

/* ================= AC state + IRext ================= */
static t_remote_ac_status s_ac = {
    .ac_display = 0, .ac_sleep = 0, .ac_timer = 0,
    .ac_power = AC_POWER_ON, .ac_mode = AC_MODE_COOL, .ac_temp = AC_TEMP_24,
    .ac_wind_dir = AC_SWING_ON, .ac_wind_speed = AC_WS_AUTO, .change_wind_direction = 0,
};
static int s_cur_remote = 0;
static bool s_remote_open = false;
static SemaphoreHandle_t s_ir_mutex = NULL;

static const char *mode_name(t_ac_mode m)
{
    switch (m) { case AC_MODE_COOL: return "COOL"; case AC_MODE_HEAT: return "HEAT";
    case AC_MODE_AUTO: return "AUTO"; case AC_MODE_FAN: return "FAN"; case AC_MODE_DRY: return "DRY";
    default: return "?"; }
}
static const char *speed_name(t_ac_wind_speed s)
{
    switch (s) { case AC_WS_AUTO: return "AUTO"; case AC_WS_LOW: return "LOW";
    case AC_WS_MEDIUM: return "MED"; case AC_WS_HIGH: return "HIGH"; default: return "?"; }
}

static bool open_remote(int idx)
{
    if (idx < 0 || idx >= (int)REMOTE_COUNT) return false;
    if (s_remote_open) { ir_close(); s_remote_open = false; }
    const remote_bin_t *r = &s_remotes[idx];
    UINT16 len = (UINT16)(r->end - r->start);
    if (ir_binary_open(REMOTE_CATEGORY_AC, 1, (UINT8 *)r->start, len) != IR_DECODE_SUCCEEDED) {
        ESP_LOGE(TAG, "ir_binary_open failed for %s", r->label);
        return false;
    }
    s_cur_remote = idx; s_remote_open = true;
    ESP_LOGI(TAG, "opened remote [%d] %s (%u bytes)", idx, r->label, (unsigned)len);
    return true;
}

static void ac_send(uint8_t key_code, const char *what)
{
    static UINT16 tx[USER_DATA_SIZE];
    if (xSemaphoreTake(s_ir_mutex, portMAX_DELAY) != pdTRUE) return;
    if (!s_remote_open) { ESP_LOGE(TAG, "no remote open"); xSemaphoreGive(s_ir_mutex); return; }
    UINT16 len = ir_decode(key_code, tx, &s_ac);
    if (len == 0) { ESP_LOGW(TAG, "decode returned 0 for %s", what); xSemaphoreGive(s_ir_mutex); return; }
    ir_send(tx, len);
    vTaskDelay(pdMS_TO_TICKS(40));
    ir_send(tx, len);
    xSemaphoreGive(s_ir_mutex);
    ESP_LOGI(TAG, "sent %-8s  power=%s mode=%s temp=%d speed=%s swing=%s",
             what, s_ac.ac_power == AC_POWER_ON ? "ON" : "OFF", mode_name(s_ac.ac_mode),
             16 + (int)s_ac.ac_temp, speed_name(s_ac.ac_wind_speed),
             s_ac.ac_wind_dir == AC_SWING_ON ? "SWING" : "FIX");
}

/* working Xiaomi frame (kk_3_90_8101, index 1) */
static int s_xi = 1;

static void send_xi(int i)
{
    if (i < 0 || i >= (int)XIAOMI_PAT_COUNT) return;
    if (xSemaphoreTake(s_ir_mutex, portMAX_DELAY) != pdTRUE) return;
    ir_set_carrier(xiaomi_pats[i].freq);
    ir_send(xiaomi_pats[i].data, xiaomi_pats[i].len);
    ir_set_carrier(38000);
    xSemaphoreGive(s_ir_mutex);
    ESP_LOGI(TAG, "sent xiaomi[%d] %s @%u", i, xiaomi_pats[i].label, (unsigned)xiaomi_pats[i].freq);
}

/* send a named Xiaomi state frame (e.g. "mode_heat", "temp_26", "fan_1", "wind_3", "b4_7") */
static void send_state_label(const char *label)
{
    for (unsigned i = 0; i < XIAOMI_STATE_COUNT; i++) {
        if (strcmp(xiaomi_states[i].label, label) == 0) {
            if (xSemaphoreTake(s_ir_mutex, portMAX_DELAY) != pdTRUE) return;
            ir_set_carrier(xiaomi_states[i].freq);
            ir_send(xiaomi_states[i].data, xiaomi_states[i].len);
            ir_set_carrier(38000);
            xSemaphoreGive(s_ir_mutex);
            ESP_LOGI(TAG, "sent state %s", label);
            return;
        }
    }
    for (unsigned i = 0; i < XIAOMI_OFF_COUNT; i++) {
        if (strcmp(xiaomi_offs[i].label, label) == 0) {
            if (xSemaphoreTake(s_ir_mutex, portMAX_DELAY) != pdTRUE) return;
            ir_set_carrier(xiaomi_offs[i].freq);
            ir_send(xiaomi_offs[i].data, xiaomi_offs[i].len);
            ir_set_carrier(38000);
            xSemaphoreGive(s_ir_mutex);
            ESP_LOGI(TAG, "sent off %s", label);
            return;
        }
    }
    ESP_LOGW(TAG, "unknown state label: %s", label);
}

/* ---- full state frame synthesis (kk_3_90_8101) ---- */
static int s_d_power = 1;   /* 1=on 0=off */
static int s_d_mode = 0;    /* 0cool 1heat 2auto 3fan 4dry */
static int s_d_temp = 26;
static int s_d_fan = 0;     /* 0auto 1low 2med 3high */
static int s_d_wind = 0;    /* 0..6 */
static int s_d_sleep = 0;
static int s_d_turbo = 0;
static uint16_t s_full[512];

static void m_write_bits(uint8_t *b, int len, int start, int end, int value)
{
    int width = end - start;
    for (int o = 0; o < width; o++) {
        int pos = start + o;
        int bi = pos / 8;
        if (bi < 0 || bi >= len) continue;
        int mask = 1 << (7 - (pos % 8));
        int bit = (value >> (width - 1 - o)) & 1;
        if (bit) b[bi] |= mask; else b[bi] &= ~mask;
    }
}

static void apply_op(uint8_t *b, const m8101_op *o)
{
    for (int k = 0; k < o->n; k++)
        m_write_bits(b, M8101_BASE_LEN, o->op[k][0], o->op[k][1], o->op[k][2]);
}

static int build_8101(void)
{
    uint8_t b[M8101_BASE_LEN];
    memcpy(b, M8101_BASE, M8101_BASE_LEN);
    if (s_d_temp >= 16 && s_d_temp <= 30) apply_op(b, &M8101_TEMP[s_d_temp - 16]);
    if (s_d_fan >= 0 && s_d_fan < M8101_NFAN) apply_op(b, &M8101_FAN[s_d_fan]);
    if (s_d_wind >= 0 && s_d_wind < M8101_NWIND) apply_op(b, &M8101_WIND[s_d_wind]);
    if (s_d_mode >= 0 && s_d_mode < M8101_NMODE) apply_op(b, &M8101_MODE[s_d_mode]);
    if (s_d_sleep) b[8] = (b[8] & 0xF8) | 0x01;      /* sleep (Lua ext22) */
    else if (s_d_turbo) b[8] = (b[8] & 0xF8) | 0x07; /* turbo (Lua ext8) */
    if (s_d_power) b[5] |= 0x04; else b[5] &= ~0x04;
    int sum = 0;
    for (int i = 0; i < M8101_BASE_LEN - 1; i++) sum += b[i];
    b[M8101_BASE_LEN - 1] = sum & 0xFF;
    int n = 0;
    for (unsigned i = 0; i < sizeof(M8101_LEAD) / sizeof(M8101_LEAD[0]); i++) s_full[n++] = M8101_LEAD[i];
    for (int i = 0; i < M8101_BASE_LEN; i++) {
        for (int bit = 0; bit < 8; bit++) {
            int v = (b[i] >> bit) & 1;
            const uint16_t *pat = v ? M8101_ONE : M8101_ZERO;
            s_full[n++] = pat[0]; s_full[n++] = pat[1];
        }
    }
    s_full[n++] = M8101_ONE[0];
    if (n % 2) s_full[n++] = 1000;
    return n;
}

static void send_full(void)
{
    if (xSemaphoreTake(s_ir_mutex, portMAX_DELAY) != pdTRUE) return;
    int n = build_8101();
    ir_set_carrier(M8101_FREQ);
    ir_send(s_full, n);
    ir_set_carrier(38000);
    xSemaphoreGive(s_ir_mutex);
    ESP_LOGI(TAG, "full pwr=%d mode=%d temp=%d fan=%d wind=%d",
             s_d_power, s_d_mode, s_d_temp, s_d_fan, s_d_wind);
}

static void print_status(void)
{
    printf("power=%s mode=%s temp=%d speed=%s swing=%s (remote [%d] %s)\n",
           s_ac.ac_power == AC_POWER_ON ? "ON" : "OFF", mode_name(s_ac.ac_mode),
           16 + (int)s_ac.ac_temp, speed_name(s_ac.ac_wind_speed),
           s_ac.ac_wind_dir == AC_SWING_ON ? "SWING" : "FIX",
           s_cur_remote, s_remotes[s_cur_remote].label);
}

/* ================= MQTT publish ================= */
static void mqtt_publish_str(const char *topic, const char *data)
{
    if (s_mqtt == NULL || !s_mqtt_up) return;
    esp_mqtt_client_publish(s_mqtt, topic, data, 0, 1, 0);
    ESP_LOGI(TAG, "PUB %s -> %s", topic, data);
}

static void publish_state(void)
{
    char buf[160];
    snprintf(buf, sizeof(buf),
             "{\"power\":%d,\"mode\":%d,\"temp\":%d,\"fan\":%d,\"wind\":%d,\"sleep\":%d,\"turbo\":%d}",
             s_d_power, s_d_mode, s_d_temp, s_d_fan, s_d_wind, s_d_sleep, s_d_turbo);
    mqtt_publish_str(TOPIC_STATE, buf);
}

/* ================= command handling ================= */
static void do_cmd(char c);
static void sweep_off_from(int start);

static void handle_json_command(const char *json, int len)
{
    cJSON *root = cJSON_ParseWithLength(json, len);
    if (root == NULL) { ESP_LOGW(TAG, "bad json: %.*s", len, json); return; }
    cJSON *it;

    it = cJSON_GetObjectItem(root, "power");
    if (it) {
        bool on = cJSON_IsBool(it) ? cJSON_IsTrue(it) : (cJSON_IsNumber(it) && it->valueint != 0);
        s_d_power = on ? 1 : 0;
        s_ac.ac_power = on ? AC_POWER_ON : AC_POWER_OFF;
    }
    it = cJSON_GetObjectItem(root, "mode");
    if (it && cJSON_IsNumber(it) && it->valueint >= 0 && it->valueint < 5) {
        s_d_mode = it->valueint;
        s_ac.ac_mode = (t_ac_mode)it->valueint;
    }
    it = cJSON_GetObjectItem(root, "temp");
    if (it && cJSON_IsNumber(it) && it->valueint >= 16 && it->valueint <= 30) {
        s_d_temp = it->valueint;
        s_ac.ac_temp = (t_ac_temperature)(it->valueint - 16);
    }
    it = cJSON_GetObjectItem(root, "fan");
    if (it && cJSON_IsNumber(it) && it->valueint >= 0 && it->valueint < 4) {
        s_d_fan = it->valueint;
        s_ac.ac_wind_speed = (t_ac_wind_speed)it->valueint;
    }
    it = cJSON_GetObjectItem(root, "wind");
    if (it == NULL) it = cJSON_GetObjectItem(root, "swing");
    if (it && cJSON_IsNumber(it) && it->valueint >= 0 && it->valueint < 7) {
        s_d_wind = it->valueint;
    }
    it = cJSON_GetObjectItem(root, "sleep");
    if (it) {
        int v = cJSON_IsBool(it) ? cJSON_IsTrue(it) : (cJSON_IsNumber(it) && it->valueint != 0);
        s_d_sleep = v ? 1 : 0;
        if (s_d_sleep) s_d_turbo = 0;
    }
    it = cJSON_GetObjectItem(root, "turbo");
    if (it) {
        int v = cJSON_IsBool(it) ? cJSON_IsTrue(it) : (cJSON_IsNumber(it) && it->valueint != 0);
        s_d_turbo = v ? 1 : 0;
        if (s_d_turbo) s_d_sleep = 0;
    }
    cJSON_Delete(root);

    send_full();
    publish_state();
}

static void handle_command(const char *s, int len)
{
    if (len >= 1 && s[0] == '{') { handle_json_command(s, len); return; }
    if (len >= 1 && s[0] == 'O') {
        int start = (len > 1) ? atoi(s + 1) : 1;
        sweep_off_from(start - 1);
        return;
    }
    if (len >= 2 && s[0] == '@') {
        char lbl[32];
        int n = len - 1 < (int)sizeof(lbl) - 1 ? len - 1 : (int)sizeof(lbl) - 1;
        memcpy(lbl, s + 1, n); lbl[n] = 0;
        send_state_label(lbl);
        publish_state();
        return;
    }
    if (len == 2 && s[0] == 'o' && (s[1] == 'n' || s[1] == 'N')) {
        s_d_power = 1; s_ac.ac_power = AC_POWER_ON; send_full(); publish_state(); return;
    }
    if (len == 3 && s[0] == 'o' && s[1] == 'f' && s[2] == 'f') {
        s_d_power = 0; s_ac.ac_power = AC_POWER_OFF; send_full(); publish_state(); return;
    }
    for (int i = 0; i < len; i++) do_cmd(s[i]);
    publish_state();
}

/* ================= MQTT ================= */
static void mqtt_event_handler(void *args, esp_event_base_t base, int32_t id, void *data)
{
    esp_mqtt_event_handle_t ev = (esp_mqtt_event_handle_t)data;
    switch ((esp_mqtt_event_id_t)id) {
    case MQTT_EVENT_CONNECTED:
        s_mqtt_up = true;
        ESP_LOGI(TAG, "MQTT connected to %s", MQTT_URI);
        esp_mqtt_client_subscribe(s_mqtt, TOPIC_CMD, 1);
        publish_state();
        break;
    case MQTT_EVENT_DISCONNECTED:
        s_mqtt_up = false;
        ESP_LOGW(TAG, "MQTT disconnected");
        break;
    case MQTT_EVENT_DATA: {
        static char buf[512];
        int n = ev->data_len < (int)sizeof(buf) - 1 ? ev->data_len : (int)sizeof(buf) - 1;
        memcpy(buf, ev->data, n);
        buf[n] = 0;
        ESP_LOGI(TAG, "MQTT RX %.*s : %s", ev->topic_len, ev->topic, buf);
        if (ev->topic_len == (int)strlen(TOPIC_CMD) && strncmp(ev->topic, TOPIC_CMD, ev->topic_len) == 0) {
            handle_command(buf, n);
        }
        break;
    }
    case MQTT_EVENT_ERROR:
        ESP_LOGW(TAG, "MQTT error");
        break;
    default:
        break;
    }
}

static void mqtt_start(void)
{
    esp_mqtt_client_config_t cfg = {
        .broker.address.uri = MQTT_URI,
        .credentials.client_id = MQTT_CLIENT_ID,
        .session.keepalive = 30,
        .network.reconnect_timeout_ms = 3000,
    };
    s_mqtt = esp_mqtt_client_init(&cfg);
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(s_mqtt, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL));
    ESP_ERROR_CHECK(esp_mqtt_client_start(s_mqtt));
}

static void heartbeat_task(void *arg)
{
    (void)arg;
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(30000));
        publish_state();
    }
}

/* ================= WiFi ================= */
static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "WiFi lost, reconnecting...");
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "WiFi got IP: " IPSTR, IP2STR(&e->ip_info.ip));
        xEventGroupSetBits(s_wifi_evt, WIFI_CONNECTED_BIT);
    }
}

static void wifi_init(void)
{
    s_wifi_evt = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL));
    wifi_config_t wc = { 0 };
    strncpy((char *)wc.sta.ssid, WIFI_SSID, sizeof(wc.sta.ssid) - 1);
    strncpy((char *)wc.sta.password, WIFI_PASS, sizeof(wc.sta.password) - 1);
    wc.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_LOGI(TAG, "connecting to WiFi \"%s\" ...", WIFI_SSID);
    xEventGroupWaitBits(s_wifi_evt, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
}

/* ================= serial console ================= */
static void uart_console_init(void)
{
    uart_config_t uc = {
        .baud_rate = 115200, .data_bits = UART_DATA_8_BITS, .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1, .flow_ctrl = UART_HW_FLOWCTRL_DISABLE, .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 1024, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(UART_NUM_0, &uc));
}

static void print_help(void)
{
    printf("\n=== serial: p/m/+/-/f/w  i=status o=pub 1..5=remote a=sweep x=matrix z=xiaomi c/v=diag h=help ===\n");
    printf("=== mqtt: pub to ac/cmd  e.g. {\"power\":1,\"mode\":0,\"temp\":26} or p / on / off ===\n\n");
}

static void sweep_matrix(void)
{
    const int freqs[] = { 38000, 36000, 40000, 56000 };
    for (int fi = 0; fi < 4; fi++) {
        ir_set_carrier(freqs[fi]);
        for (int k = 0; k < (int)REMOTE_COUNT; k++) {
            t_remote_ac_status saved = s_ac;
            if (!open_remote(k)) continue;
            s_ac = saved;
            s_ac.ac_power = AC_POWER_ON;
            char msg[80];
            snprintf(msg, sizeof(msg), "try freq=%d code=%d %s", freqs[fi], k, s_remotes[k].label);
            ESP_LOGI(TAG, "%s", msg);
            mqtt_publish_str(TOPIC_TRY, msg);
            ac_send(KEY_AC_POWER, "POWER(on)");
            vTaskDelay(pdMS_TO_TICKS(3000));
        }
    }
    ir_set_carrier(38000);
    open_remote(s_cur_remote);
    publish_state();
}

static void sweep_xiaomi(void)
{
    for (unsigned i = 0; i < XIAOMI_PAT_COUNT; i++) {
        ir_set_carrier(xiaomi_pats[i].freq);
        char msg[72];
        snprintf(msg, sizeof(msg), "x %u/%u %s", i + 1, (unsigned)XIAOMI_PAT_COUNT, xiaomi_pats[i].label);
        ESP_LOGI(TAG, "%s", msg);
        mqtt_publish_str(TOPIC_TRY, msg);
        ir_send(xiaomi_pats[i].data, xiaomi_pats[i].len);
        vTaskDelay(pdMS_TO_TICKS(2000));
    }
    ir_set_carrier(38000);
    publish_state();
}

static void sweep_states(void)
{
    for (unsigned i = 0; i < XIAOMI_STATE_COUNT; i++) {
        ir_set_carrier(xiaomi_states[i].freq);
        char msg[72];
        snprintf(msg, sizeof(msg), "z %u/%u %s", i + 1, (unsigned)XIAOMI_STATE_COUNT, xiaomi_states[i].label);
        ESP_LOGI(TAG, "%s", msg);
        mqtt_publish_str(TOPIC_TRY, msg);
        ir_send(xiaomi_states[i].data, xiaomi_states[i].len);
        vTaskDelay(pdMS_TO_TICKS(2200));
    }
    ir_set_carrier(38000);
    publish_state();
}

static void sweep_off_from(int start)
{
    if (start < 0) start = 0;
    for (unsigned i = (unsigned)start; i < XIAOMI_OFF_COUNT; i++) {
        ir_set_carrier(xiaomi_offs[i].freq);
        char msg[72];
        snprintf(msg, sizeof(msg), "o %u/%u %s", i + 1, (unsigned)XIAOMI_OFF_COUNT, xiaomi_offs[i].label);
        ESP_LOGI(TAG, "%s", msg);
        mqtt_publish_str(TOPIC_TRY, msg);
        ir_send(xiaomi_offs[i].data, xiaomi_offs[i].len);
        publish_state();
        vTaskDelay(pdMS_TO_TICKS(3000));
    }
    ir_set_carrier(38000);
    publish_state();
}

static void do_cmd(char c)
{
    if (!s_remote_open) { open_remote(0); return; }
    switch (c) {
    case 'p':
        s_d_power ^= 1;
        s_ac.ac_power = s_d_power ? AC_POWER_ON : AC_POWER_OFF;
        send_full(); publish_state(); break;
    case 'm':
        s_ac.ac_mode = (t_ac_mode)((s_ac.ac_mode + 1) % AC_MODE_MAX);
        ac_send(KEY_AC_MODE_SWITCH, "MODE"); publish_state(); break;
    case '+': case '=':
        if (s_ac.ac_temp < AC_TEMP_30) s_ac.ac_temp = (t_ac_temperature)(s_ac.ac_temp + 1);
        ac_send(KEY_AC_TEMP_PLUS, "TEMP+"); publish_state(); break;
    case '-': case '_':
        if (s_ac.ac_temp > AC_TEMP_16) s_ac.ac_temp = (t_ac_temperature)(s_ac.ac_temp - 1);
        ac_send(KEY_AC_TEMP_MINUS, "TEMP-"); publish_state(); break;
    case 'f':
        s_ac.ac_wind_speed = (t_ac_wind_speed)((s_ac.ac_wind_speed + 1) % AC_WS_MAX);
        ac_send(KEY_AC_WIND_SPEED, "FAN"); publish_state(); break;
    case 'w':
        s_ac.ac_wind_dir = (s_ac.ac_wind_dir == AC_SWING_ON) ? AC_SWING_OFF : AC_SWING_ON;
        ac_send(KEY_AC_WIND_SWING, "SWING"); publish_state(); break;
    case 'i': print_status(); break;
    case 'o': publish_state(); break;
    case 'g': send_xi(s_xi); break;
    case 'c': {
        rmt_symbol_word_t sym = { .level0 = 1, .duration0 = 3000000, .level1 = 0, .duration1 = 0 };
        rmt_transmit_config_t tc = { .loop_count = 0 };
        ESP_LOGI(TAG, "DIAG: steady 38kHz 3s"); ESP_ERROR_CHECK(rmt_transmit(s_tx_channel, s_copy_encoder, &sym, sizeof(sym), &tc));
        rmt_tx_wait_all_done(s_tx_channel, portMAX_DELAY); break;
    }
    case 'v': {
        rmt_symbol_word_t sym = { .level0 = 0, .duration0 = 3000000, .level1 = 0, .duration1 = 0 };
        rmt_transmit_config_t tc = { .loop_count = 0 };
        ESP_LOGI(TAG, "DIAG: steady LOW 3s"); ESP_ERROR_CHECK(rmt_transmit(s_tx_channel, s_copy_encoder, &sym, sizeof(sym), &tc));
        rmt_tx_wait_all_done(s_tx_channel, portMAX_DELAY); break;
    }
    case '1': case '2': case '3': case '4': case '5': open_remote(c - '1'); break;
    case 'a': {
        for (int k = 0; k < (int)REMOTE_COUNT; k++) {
            t_remote_ac_status saved = s_ac;
            if (!open_remote(k)) continue;
            s_ac = saved; s_ac.ac_power = AC_POWER_ON;
            ESP_LOGI(TAG, ">>> sweep variant %d", k);
            ac_send(KEY_AC_POWER, "POWER(on)");
            vTaskDelay(pdMS_TO_TICKS(3000));
        }
        open_remote(s_cur_remote); break;
    }
    case 'x': sweep_matrix(); break;
    case 'z': sweep_xiaomi(); break;
    case 'Z': sweep_states(); break;
    case 'O': sweep_off_from(0); break;
    case 'h': case '?': print_help(); break;
    default: break;
    }
}

void app_main(void)
{
    esp_chip_info_t info;
    esp_chip_info(&info);
    printf("\n=====================================================\n");
    printf("   ESP32-C3  IRext Konka AC  +  MQTT(%s)\n", MQTT_URI);
    printf("=====================================================\n");
    printf(" chip : ESP32-C3 rev v%d.%d, %d core(s)\n", info.revision / 100, info.revision % 100, info.cores);
    printf(" IR   : GPIO4 @ 38kHz\n=====================================================\n\n");

    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    s_ir_mutex = xSemaphoreCreateMutex();
    ir_tx_init();
    uart_console_init();
    if (!open_remote(0)) ESP_LOGE(TAG, "failed to open embedded remote 0");
    print_help();

    wifi_init();
    mqtt_start();
    xTaskCreate(heartbeat_task, "hb", 4096, NULL, 4, NULL);

    while (1) {
        uint8_t ch = 0;
        if (uart_read_bytes(UART_NUM_0, &ch, 1, pdMS_TO_TICKS(200)) > 0) {
            do_cmd(ch);
        }
    }
}
