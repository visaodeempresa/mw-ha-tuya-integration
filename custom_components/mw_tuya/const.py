"""Constantes e mapeamentos da integração híbrida MW Tuya Integration."""

from __future__ import annotations

DOMAIN = "mw_tuya"

CONF_ACCOUNT_NAME = "account_name"
CONF_REGION = "region"
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_UID = "uid"

CONF_SELECTED_DEVICES = "selected_devices"
CONF_SELECTED_SCENES = "selected_scenes"
CONF_LOCAL_HOSTS = "local_hosts"
CONF_LOCAL_VERSIONS = "local_versions"
CONF_ROUTING_MODE = "routing_mode"
CONF_SCAN_INTERVAL = "scan_interval"

ROUTING_HYBRID_LOCAL_FIRST = "hybrid_local_first"
ROUTING_LOCAL_ONLY = "local_only"
ROUTING_CLOUD_ONLY = "cloud_only"

ROUTING_MODES: list[str] = [
    ROUTING_HYBRID_LOCAL_FIRST,
    ROUTING_LOCAL_ONLY,
    ROUTING_CLOUD_ONLY,
]

DEFAULT_SCAN_INTERVAL = 30
STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}_catalog"

REGIONS: dict[str, str] = {
    "us": "https://openapi.tuyaus.com",
    "eu": "https://openapi.tuyaeu.com",
    "cn": "https://openapi.tuyacn.com",
    "in": "https://openapi.tuyain.com",
    "sg": "https://openapi-sg.iotbing.com",
    "we": "https://openapi-ueaz.tuyaus.com",
    "ue": "https://openapi-weaz.tuyaeu.com",
}

# Categorias que são exclusivamente Cloud ou passivas (sensores adormecidos / hubs IR)
CLOUD_ONLY_CATEGORIES: set[str] = {
    "wnykq",
    "infrared_ac",
    "infrared_tv",
    "infrared_fan",
    "infrared_box",
    "infrared_stb",
    "infrared_diy",
    "sp",
    "ej",
}

# Rótulos legíveis de categorias Tuya (extraídos do catálogo mcp-smarthome)
CATEGORY_LABELS: dict[str, str] = {
    "cz": "Tomada Inteligente",
    "pc": "Régua Inteligente",
    "tdq": "Interruptor / Disjuntor",
    "kg": "Interruptor",
    "dj": "Lâmpada Inteligente",
    "dd": "Fita LED",
    "xdd": "Spot / Luminária",
    "cl": "Cortina / Persiana",
    "mc": "Motor de Janela",
    "mcs": "Sensor Porta/Janela",
    "pir": "Sensor de Movimento PIR",
    "hps": "Sensor de Presença mmWave",
    "sos": "Botão SOS",
    "zd": "Sensor de Vibração",
    "wsdcg": "Sensor Temperatura/Umidade",
    "ldcg": "Sensor T/H/Luminosidade",
    "zwjcy": "Sensor de Umidade/Temperatura",
    "jqbj": "Monitor Qualidade do Ar",
    "kj": "Purificador de Ar",
    "jsq": "Umidificador",
    "kt": "Ar-Condicionado",
    "sp": "Câmera IP",
    "sd": "Aspirador Robô",
    "wnykq": "Hub Infravermelho Universal",
    "wg2": "Gateway / Hub Zigbee",
    "wfcon": "Sirene / Alarme Wi-Fi",
    "wxkg": "Botão / Controle de Cena",
    "ej": "Fone Inteligente",
    "qt": "Dispositivo Customizado",
}

# Mapeamento padrão entre códigos semânticos da Tuya Cloud e IDs de DP locais (protocolo 3.3/3.4)
CODE_TO_DEFAULT_DP: dict[str, int] = {
    "switch": 1,
    "switch_1": 1,
    "switch_2": 2,
    "switch_3": 3,
    "switch_4": 4,
    "switch_5": 5,
    "switch_6": 6,
    "switch_usb1": 7,
    "switch_usb2": 8,
    "switch_led": 20,
    "bright_value": 22,
    "bright_value_v2": 22,
    "temp_value": 23,
    "temp_value_v2": 23,
    "work_mode": 21,
    "cur_current": 18,
    "cur_power": 19,
    "cur_voltage": 20,
    "add_ele": 17,
    "control": 1,
    "percent_control": 2,
    "percent_state": 3,
    "fan_speed_enum": 3,
    "fan_speed": 3,
    "mode": 4,
    "Child_Lock": 7,
    "child_lock": 7,
    "temp_set": 2,
    "temp_current": 3,
    "humidity_set": 103,
    "humidity_current": 14,
    "va_temperature": 1,
    "va_humidity": 2,
    "battery_percentage": 4,
}

# Mapeamento inverso por categoria para traduzir leituras locais (DP numérico -> code Cloud)
PLUG_DP_TO_CODE: dict[int, str] = {
    1: "switch_1",
    2: "switch_2",
    3: "switch_3",
    4: "switch_4",
    5: "switch_5",
    6: "switch_6",
    7: "switch_usb1",
    8: "switch_usb2",
    17: "add_ele",
    18: "cur_current",
    19: "cur_power",
    20: "cur_voltage",
}

LIGHT_DP_TO_CODE: dict[int, str] = {
    1: "switch_led",
    20: "switch_led",
    21: "work_mode",
    22: "bright_value_v2",
    23: "temp_value_v2",
}

COVER_DP_TO_CODE: dict[int, str] = {
    1: "control",
    2: "percent_control",
    3: "percent_state",
}
