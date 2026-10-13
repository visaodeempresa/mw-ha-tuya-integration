"""Constantes e mapeamentos da integração híbrida MW Tuya Integration (`mw_tuya`)."""

from __future__ import annotations

DOMAIN = "mw_tuya"

CONF_ACCOUNT_NAME = "account_name"
CONF_REGION = "region"
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_UID = "uid"
# Sessão Smart Life (login por QR Code, mesmo canal da Tuya nativa)
CONF_SMARTLIFE = "smartlife"
CONF_USER_CODE = "user_code"

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

# Categorias que são controles virtuais IR ou fones BLE exclusivos de nuvem
CLOUD_ONLY_CATEGORIES: set[str] = {
    "infrared_ac",
    "infrared_tv",
    "infrared_fan",
    "infrared_box",
    "infrared_stb",
    "infrared_diy",
    "ej",
}

# Rótulos legíveis de categorias Tuya (extraídos do catálogo mcp-smarthome)
CATEGORY_LABELS: dict[str, str] = {
    "cz": "Tomada Inteligente",
    "pc": "Régua Inteligente",
    "tdq": "Interruptor / Disjuntor",
    "dlq": "Disjuntor / Medidor",
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

# Mapeamento padrão entre códigos semânticos da Tuya Cloud e IDs de DP locais (fallback)
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
    "countdown_1": 9,
    "countdown_2": 10,
    "countdown_3": 11,
    "countdown_4": 12,
    "countdown_5": 13,
    "countdown_6": 14,
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
    "relay_status": 38,
    "light_mode": 40,
    "child_lock": 41,
    "Child_Lock": 7,
    "control": 1,
    "percent_control": 2,
    "percent_state": 3,
    "fan_speed_enum": 3,
    "fan_speed": 3,
    "mode": 4,
    "temp_set": 2,
    "temp_current": 3,
    "humidity_set": 103,
    "humidity_current": 14,
    "va_temperature": 1,
    "va_humidity": 2,
    "battery_percentage": 4,
    "basic_indicator": 101,
    "basic_flip": 103,
    "basic_osd": 104,
    "basic_private": 105,
    "motion_switch": 134,
    "record_switch": 150,
    "record_mode": 151,
    "siren_switch": 159,
}

PLUG_DP_TO_CODE: dict[int, str] = {
    1: "switch_1",
    2: "switch_2",
    3: "switch_3",
    4: "switch_4",
    5: "switch_5",
    6: "switch_6",
    7: "switch_usb1",
    8: "switch_usb2",
    9: "countdown_1",
    10: "countdown_2",
    11: "countdown_3",
    12: "countdown_4",
    17: "add_ele",
    18: "cur_current",
    19: "cur_power",
    20: "cur_voltage",
    38: "relay_status",
    40: "light_mode",
    41: "child_lock",
}

LIGHT_DP_TO_CODE: dict[int, str] = {
    1: "switch_led",
    20: "switch_led",
    21: "work_mode",
    22: "bright_value_v2",
    23: "temp_value_v2",
    26: "countdown",
}

COVER_DP_TO_CODE: dict[int, str] = {
    1: "control",
    2: "percent_control",
    3: "percent_state",
}

# Mapa padrão de reservas DHCP / IPs locais conhecidos (device_id -> (ip, versão)).
# Pode ser sobreposto via `entry.options["local_hosts"]`, descoberta UDP 6666/6667/7000
# ou serviço `mw_tuya.set_local_host`. Não contém chaves nem segredos.
DEFAULT_LOCAL_HOSTS: dict[str, tuple[str, str]] = {
    "38400707e8db84e5dda0": ("192.168.2.100", "3.3"),
    "38400707e8db84e5de52": ("192.168.2.196", "3.3"),
    "38400707e8db84e65286": ("192.168.2.130", "3.3"),
    "70546171ecfabc7c72a6": ("192.168.2.11", "3.3"),
    "70546171ecfabc7c72d0": ("192.168.2.42", "3.3"),
    "eb07353c7cab21ce05ooqx": ("192.168.2.49", "3.3"),
    "eb07ae42491687fd313aiy": ("192.168.2.34", "3.5"),
    "eb0e26b758fb96fc07bbpx": ("192.168.2.110", "3.4"),
    "eb0e3e32783a3c4161e6sy": ("192.168.2.61", "3.3"),
    "eb1a8c2e08f3267b3bvbrf": ("192.168.2.91", "3.4"),
    "eb1dcf3cd4cc55b5bb0pag": ("192.168.2.102", "3.3"),
    "eb1dd198ab0d51225crslq": ("192.168.2.27", "3.3"),
    "eb215f5d94df0519c6hdkt": ("192.168.2.104", "3.3"),
    "eb22c60734ef67edbajarj": ("192.168.2.143", "3.5"),
    "eb244ebed2360f04914fsp": ("192.168.1.180", "3.4"),
    "eb2a205b8070f85f711uis": ("192.168.2.85", "3.4"),
    "eb2b6cfee0c40066fffs29": ("192.168.2.34", "3.5"),
    "eb2f968dc61b400c57laza": ("192.168.2.34", "3.5"),
    "eb33815d732a4aa717imsx": ("192.168.2.59", "3.4"),
    "eb355a9f878112dbf0m5nd": ("192.168.2.221", "3.3"),
    "eb3c86a1f227fd202ezfuy": ("192.168.2.34", "3.5"),
    "eb3ed339c5bbb704aedrqp": ("192.168.2.34", "3.5"),
    "eb40e25c043fa6e250lu8f": ("192.168.2.160", "3.3"),
    "eb4d40d150fbead1e9ak0a": ("192.168.2.23", "3.3"),
    "eb53698f81019a3f4aa3q7": ("192.168.2.144", "3.3"),
    "eb587156f50e168a5d3myo": ("192.168.2.12", "3.4"),
    "eb5acea05d1fbc3aa1ar6u": ("192.168.2.122", "3.4"),
    "eb5cd532dc45836978vmzc": ("192.168.2.34", "3.5"),
    "eb66574e260811bcfbxear": ("192.168.2.198", "3.3"),
    "eb6ac0f21dd3acb57dxqfn": ("192.168.2.34", "3.5"),
    "eb6db9be0437857ef5my7z": ("192.168.2.31", "3.4"),
    "eb6e3e02a0b127d87aqbmv": ("192.168.2.139", "3.4"),
    "eb748cc401bfeb6b16vvdz": ("192.168.2.14", "3.3"),
    "eb77229b2a9fafa74ee2pc": ("192.168.2.211", "3.3"),
    "eb7a08bb5dc94151c1aq0c": ("192.168.2.34", "3.5"),
    "eb7a33d5d26d37d87euu2w": ("192.168.2.89", "3.4"),
    "eb7eaf3f18b7c8dbb132ve": ("192.168.2.34", "3.5"),
    "eb816a4644de964e1ecglm": ("192.168.2.46", "3.4"),
    "eb8394a828d20e7d0eygej": ("192.168.1.137", "3.4"),
    "eb8490c90dc53f9925h1ak": ("192.168.2.35", "3.4"),
    "eb888687d90b861b85cphf": ("192.168.2.36", "3.4"),
    "eb93be8f07133be5cdymbk": ("192.168.1.29", "3.4"),
    "eb95eb34b8477adc07rqza": ("192.168.2.65", "3.4"),
    "eb96a58acc7d3b713aqaoz": ("192.168.2.19", "3.4"),
    "eb97fe6f36871601e2e4am": ("192.168.2.75", "3.4"),
    "eb9822bfdf6129be4ezfao": ("192.168.2.34", "3.5"),
    "eb9dd8497774fa050bwyjl": ("192.168.1.11", "3.4"),
    "eb9ed27d957425eeccwoin": ("192.168.2.63", "3.3"),
    "eba1f33e7fc7c074bfvsua": ("192.168.2.26", "3.4"),
    "eba7cfe854eb17d16chi02": ("192.168.2.34", "3.5"),
    "eba811b7dfea45ffbemko0": ("192.168.2.140", "3.3"),
    "eba828ac9f3f474414mj2e": ("192.168.2.41", "3.4"),
    "ebae2c05e192b4a25dhrpj": ("192.168.2.25", "3.3"),
    "ebb03b7b58f1052a94ccqp": ("192.168.2.79", "3.4"),
    "ebb15bd5dc1125f874ltrq": ("192.168.2.180", "3.3"),
    "ebb4e97cd1c1eb72c3sdxu": ("192.168.2.58", "3.4"),
    "ebbbe9ab88eac25673tkv9": ("192.168.2.80", "3.4"),
    "ebbfd117c510d931eda6as": ("192.168.2.76", "3.4"),
    "ebc0500899bf88b188h5k1": ("192.168.2.56", "3.3"),
    "ebcbe7a36f586af1c7iyix": ("192.168.2.131", "3.3"),
    "ebcc203220f73515cfgmza": ("192.168.2.7", "3.4"),
    "ebd1df7ea7b4d33c33odsq": ("192.168.2.67", "3.3"),
    "ebd8e5e18ccc132a82mrag": ("192.168.2.126", "3.4"),
    "ebd974663b587a2777a8rk": ("192.168.1.196", "3.4"),
    "ebdd8148c3a99185c6dyae": ("192.168.1.154", "3.4"),
    "ebdf80e9aa1c24b580kfqm": ("192.168.2.95", "3.4"),
    "ebe1ff878045b13491togt": ("192.168.2.77", "3.5"),
    "ebe36f6af47098bb6ej5ad": ("192.168.2.98", "3.4"),
    "ebe3fb6655c8ac457ewadu": ("192.168.2.120", "3.3"),
    "ebe4c7055182741c81sbxv": ("192.168.2.146", "3.4"),
    "ebe6aae597f0c6ed96iwaq": ("192.168.2.135", "3.3"),
    "ebe6b5635fc51a7be2jwqc": ("192.168.2.34", "3.5"),
    "ebed2f8cc4cdd921bdcjm1": ("192.168.2.15", "3.4"),
    "ebeeb92bd7f48c0ec9p1ur": ("192.168.2.39", "3.4"),
    "ebf3214e780d8936935b7j": ("192.168.2.136", "3.3"),
    "ebf6aa63f38cfc1d811kdx": ("192.168.2.10", "3.4"),
}
