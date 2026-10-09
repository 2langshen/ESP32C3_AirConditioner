idf_component_register(SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES irext esp_driver_rmt esp_timer esp_driver_uart
             esp_wifi esp_event esp_netif nvs_flash mqtt json
    EMBED_FILES
        "konka_ac_3557.bin"
        "konka_ac_3558.bin"
        "konka_ac_3559.bin"
        "konka_ac_3560.bin"
        "konka_ac_3561.bin")
