"""Tabelas de rótulos e classes usadas pela fábrica de entidades."""

from __future__ import annotations

# Categorias cuja entidade principal é cada plataforma
LIGHT_CATS = {"dj", "dd", "xdd", "fwd", "dc", "tgq", "tgkg", "gyd", "sxd", "tyndj", "fwl", "mbd"}
FAN_CATS = {"kj", "fs", "fsd", "fskg"}
COVER_CATS = {"cl", "clkg", "mc", "ckmkzq"}
HUMIDIFIER_CATS = {"jsq", "cs"}
CLIMATE_CATS = {"kt", "wk", "qn", "rs"}
CAMERA_CATS = {"sp"}
VACUUM_CATS = {"sd"}
# DPs que viram `siren`
SIREN_CODES = {"siren_switch", "alarm_switch"}
# Botões sem fio: `switch_mode1`/`switch1_value` viram `event` (push em tempo real)
EVENT_CATS = {"wxkg"}
# IR/virtuais: controlados pela integração MW Infrared — aqui não geram entidades
SKIP_CATS = {
    "infrared_ac",
    "infrared_tv",
    "infrared_fan",
    "infrared_box",
    "infrared_stb",
    "infrared_diy",
    "qt",
    "wnykq",
}

# Códigos nunca expostos (internos/brutos/calibração)
SKIP_CODES = {
    "test_bit",
    "voltage_coe",
    "electric_coe",
    "power_coe",
    "electricity_coe",
    "cycle_time",
    "random_time",
    "switch_inching",
    "cycle_timing",
    "random_timing",
    "scene_data",
    "scene_data_v2",
    "music_data",
    "control_data",
    "rhythm_mode",
    "sleep_mode",
    "wakeup_mode",
    "power_memory",
    "switch_gradient",
    "phase_a",
    "phase_b",
    "phase_c",
    "alarm_set_1",
    "alarm_set_2",
    "online_state",
    "factory_reset",
    "sd_format",
    "ptz_control",
    "ptz_stop",
    "initiative_message",
    "zll_value",
}

# code → (device_class, unidade padrão, state_class, habilitado por padrão)
SENSOR_CLASSES: dict[str, tuple[str | None, str | None, str | None, bool]] = {
    "temp_current": ("temperature", "°C", "measurement", True),
    "va_temperature": ("temperature", "°C", "measurement", True),
    "temp_indoor": ("temperature", "°C", "measurement", True),
    "humidity_value": ("humidity", "%", "measurement", True),
    "va_humidity": ("humidity", "%", "measurement", True),
    "humidity_current": ("humidity", "%", "measurement", True),
    "humidity_indoor": ("humidity", "%", "measurement", True),
    "battery_percentage": ("battery", "%", "measurement", True),
    "va_battery": ("battery", "%", "measurement", True),
    "residual_electricity": ("battery", "%", "measurement", True),
    "leftear_battery_percentage": ("battery", "%", "measurement", False),
    "rightear_battery_percentage": ("battery", "%", "measurement", False),
    "cur_power": ("power", "W", "measurement", True),
    "cur_voltage": ("voltage", "V", "measurement", True),
    "cur_current": ("current", "mA", "measurement", True),
    "add_ele": ("energy", "kWh", "total_increasing", True),
    "forward_energy_total": ("energy", "kWh", "total_increasing", True),
    "reverse_energy_total": ("energy", "kWh", "total_increasing", False),
    "supply_frequency": ("frequency", "Hz", "measurement", False),
    "power_factor": ("power_factor", None, "measurement", False),
    "co2_value": ("carbon_dioxide", "ppm", "measurement", True),
    "pm25_value": ("pm25", "µg/m³", "measurement", True),
    "pm10": ("pm10", "µg/m³", "measurement", True),
    "voc_value": ("volatile_organic_compounds", None, "measurement", True),
    "ch2o_value": (None, "mg/m³", "measurement", True),
    "bright_value": ("illuminance", "lx", "measurement", True),
    "illuminance_value": ("illuminance", "lx", "measurement", True),
    "dis_current": ("distance", "cm", "measurement", False),
    "filter_life": (None, "%", "measurement", True),
    "filter_days": (None, "d", "measurement", True),
    "edge_brush_life": (None, "%", "measurement", False),
    "clean_area": ("area", "m²", "measurement", False),
    "clean_time": ("duration", "min", "measurement", False),
}

ENUM_SENSOR_ENABLED = {"battery_state", "status", "window_state", "charge_status"}

# code → (device_class, valores que significam "ligado")
BINARY_CLASSES: dict[str, tuple[str, set[str]]] = {
    "doorcontact_state": ("door", {"true"}),
    "pir_state": ("motion", {"pir"}),
    "pir": ("motion", {"pir"}),
    "presence_state": ("occupancy", {"presence"}),
    "sos_state": ("safety", {"true"}),
    "shock_state": ("vibration", {"vibration"}),
    "watersensor_state": ("moisture", {"alarm"}),
    "smoke_sensor_status": ("smoke", {"alarm"}),
    "gas_sensor_status": ("gas", {"alarm"}),
    "window_state": ("window", {"opened"}),
    "upradar": ("occupancy", {"true"}),
    "ipc_movement_detect": ("motion", {"motion"}),
    "tamper_alarm": ("tamper", {"true"}),
    "temper_alarm": ("tamper", {"true"}),
}

# Escritas de disparo (botões)
BUTTON_CODES = {
    "filter_reset",
    "reset_filter",
    "reset_add_ele",
    "clear_energy",
    "edge_brush_life_reset",
    "reset_edge_brush",
    "restart",
    "device_restart",
    "ptz_calibration",
    "seek",
    "device_find",
}

LABELS: dict[str, str] = {
    "child_lock": "Trava infantil",
    "lock": "Trava infantil",
    "light": "Luz do painel",
    "basic_indicator": "LED indicador",
    "indicator": "LED indicador",
    "basic_private": "Modo privacidade",
    "basic_osd": "Marca d'água de horário",
    "basic_flip": "Inverter imagem",
    "basic_nightvision": "Visão noturna",
    "motion_switch": "Alarme de movimento",
    "motion_sensitivity": "Sensibilidade de movimento",
    "motion_tracking": "Rastreamento de movimento",
    "record_switch": "Gravação em cartão SD",
    "record_mode": "Modo de gravação",
    "siren_switch": "Sirene",
    "sleep": "Modo noturno",
    "mute": "Silenciar",
    "do_not_disturb": "Não perturbe",
    "relay_status": "Estado após queda de energia",
    "light_mode": "Modo do LED indicador",
    "switch_type": "Tipo de interruptor",
    "level": "Nível de névoa",
    "countdown_set": "Timer",
    "countdown": "Timer",
    "far_detection": "Distância máxima de detecção",
    "near_detection": "Distância mínima de detecção",
    "presence_time": "Tempo de retenção",
    "no_one_time": "Atraso sem presença",
    "motion_sensitivity_value": "Sensibilidade em movimento",
    "motionless_sensitivity": "Sensibilidade parado",
    "pir_sensitivity": "Sensibilidade PIR",
    "bright_sensitivity": "Sensibilidade de luminosidade",
    "filter_reset": "Resetar filtro",
    "reset_add_ele": "Zerar medidor de energia",
    "clear_energy": "Zerar medidor de energia",
    "edge_brush_life_reset": "Resetar escova lateral",
    "seek": "Localizar",
    "device_find": "Localizar",
    "temp_current": "Temperatura",
    "va_temperature": "Temperatura",
    "humidity_value": "Umidade",
    "va_humidity": "Umidade",
    "battery_percentage": "Bateria",
    "residual_electricity": "Bateria",
    "battery_state": "Estado da bateria",
    "cur_power": "Potência",
    "cur_voltage": "Tensão",
    "cur_current": "Corrente",
    "add_ele": "Energia",
    "forward_energy_total": "Energia",
    "reverse_energy_total": "Energia reversa",
    "supply_frequency": "Frequência",
    "power_factor": "Fator de potência",
    "co2_value": "CO₂",
    "pm25_value": "PM2.5",
    "voc_value": "TVOC",
    "ch2o_value": "Formaldeído",
    "bright_value": "Luminosidade",
    "illuminance_value": "Luminosidade",
    "dis_current": "Distância do alvo",
    "filter_life": "Vida útil do filtro",
    "filter_days": "Dias restantes do filtro",
    "doorcontact_state": "Contato",
    "pir_state": "Movimento",
    "presence_state": "Presença",
    "window_state": "Janela",
    "charge_status": "Carregamento",
    "status": "Status",
    "mode": "Modo",
    "work_mode": "Modo",
}


def label_for(code: str, custom: dict[str, str]) -> str:
    if custom.get(code):
        return custom[code]
    if code in LABELS:
        return LABELS[code]
    if code.startswith("countdown_"):
        return f"Timer {code.removeprefix('countdown_')}"
    return code.replace("_", " ").strip().capitalize()
