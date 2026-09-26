idf_component_register(
    SRCS
        "main.c"
        "flight_state.c"
        "wifi_link.c"
        "cmd_parser.c"
        "crsf_tx.c"
        "chase.c"
        "sensors.c"
        "vl53l5cx_port.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES esp_driver_gpio esp_driver_i2c esp_driver_uart esp_timer log esp_rom freertos
                    esp_wifi esp_netif esp_event nvs_flash
)

idf_component_get_property(vl53l5cx_lib vl53l5cx COMPONENT_LIB)
target_link_libraries(${COMPONENT_LIB} PUBLIC ${vl53l5cx_lib})
