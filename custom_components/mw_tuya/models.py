"""Modelos de domínio e gerador de especificações de entidades unificadas (Local + Cloud).

Adaptado de `mcp_smarthome.integration.tuya.models.devices.tuya_device` e
`tuya-local-sync` para operar como um único dispositivo híbrido no Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import (
    CATEGORY_LABELS,
    CLOUD_ONLY_CATEGORIES,
    CODE_TO_DEFAULT_DP,
    COVER_DP_TO_CODE,
    DEFAULT_LOCAL_HOSTS,
    LIGHT_DP_TO_CODE,
    PLUG_DP_TO_CODE,
)


@dataclass(slots=True)
class EntitySpec:
    """Especificação de uma entidade do Home Assistant derivada dos DPs do dispositivo."""

    platform: str
    code: str
    name: str
    dp_id: int | None = None
    device_class: str | None = None
    unit: str | None = None
    scale: float = 1.0
    state_class: str | None = None
    entity_category: str | None = None
    options: list[str] = field(default_factory=list)
    min_value: float = 0.0
    max_value: float = 100.0
    step: float = 1.0


@dataclass(slots=True)
class MwTuyaScene:
    """Representa uma cena Tap-to-Run de uma conta Tuya."""

    scene_id: str
    name: str
    home_id: str
    home_name: str = ""
    enabled: bool = True
    background: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "name": self.name,
            "home_id": self.home_id,
            "home_name": self.home_name,
            "enabled": self.enabled,
            "background": self.background,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MwTuyaScene:
        return cls(
            scene_id=str(data.get("scene_id") or data.get("id") or ""),
            name=str(data.get("name") or "").strip(),
            home_id=str(data.get("home_id") or ""),
            home_name=str(data.get("home_name") or ""),
            enabled=bool(data.get("enabled", True)),
            background=str(data.get("background") or ""),
        )


@dataclass(slots=True)
class MwTuyaDevice:
    """Representa um dispositivo unificado (Local + Cloud) de uma conta Tuya."""

    device_id: str
    name: str
    category: str = ""
    product_id: str = ""
    product_name: str = ""
    model: str = ""
    uuid: str = ""
    online: bool = False
    ip_wan: str = ""
    local_ip: str = ""
    local_version: str = "3.3"
    local_key: str = ""
    sub: bool = False
    node_id: str = ""
    owner_id: str = ""
    uid: str = ""
    icon: str = ""
    status: dict[str, Any] = field(default_factory=dict)
    raw_dps: dict[int, Any] = field(default_factory=dict)
    dp_map: dict[str, int] = field(default_factory=dict)
    custom_names: dict[str, str] = field(default_factory=dict)

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, f"Dispositivo ({self.category or 'outro'})")

    @property
    def has_valid_local_key(self) -> bool:
        return bool(self.local_key and "*" not in self.local_key and len(self.local_key) >= 16)

    @property
    def supports_local(self) -> bool:
        """True quando o dispositivo possui local_key e não é exclusivo de nuvem."""
        if not self.has_valid_local_key:
            return False
        return self.category not in CLOUD_ONLY_CATEGORIES

    @property
    def is_local_configured(self) -> bool:
        return bool(self.supports_local and self.local_ip)

    @property
    def connection_badge(self) -> str:
        if self.is_local_configured:
            return f"Híbrido Local ({self.local_ip} v{self.local_version}) + Cloud"
        if self.supports_local:
            return "Cloud (Local Key pronta · aguardando IP LAN)"
        return "Cloud Only"

    def apply_shadow_properties(self, properties: list[dict[str, Any]]) -> None:
        """Aplica as propriedades do Shadow v2.0 (`code`, `dp_id`, `value`, `custom_name`)."""
        for prop in properties or []:
            if not isinstance(prop, dict):
                continue
            code = str(prop.get("code") or "")
            if not code:
                continue
            dp_id = prop.get("dp_id")
            if isinstance(dp_id, int):
                self.dp_map[code] = dp_id
            if "value" in prop and prop["value"] is not None:
                self.status[code] = prop["value"]
            cname = str(prop.get("custom_name") or "").strip()
            if cname:
                self.custom_names[code] = cname
            if code == "onvif_ip_addr" and not self.local_ip:
                ip_val = str(prop.get("value") or "").strip()
                if ip_val.startswith("192.168.") or ip_val.startswith("10."):
                    self.local_ip = ip_val

    def merge_cloud_status(self, status_list: list[dict[str, Any]] | dict[str, Any]) -> None:
        if isinstance(status_list, dict):
            self.status.update(status_list)
            return
        for item in status_list or []:
            if isinstance(item, dict) and "code" in item:
                self.status[str(item["code"])] = item.get("value")

    def merge_local_dps(self, dps: dict[str | int, Any]) -> None:
        """Mescla DPs numéricos lidos via TCP 6668 local no mapa semântico de status."""
        if not dps:
            return
        dp_map = self._dp_to_code_map()
        for raw_k, val in dps.items():
            try:
                dp_num = int(raw_k)
            except (TypeError, ValueError):
                self.status[str(raw_k)] = val
                continue
            self.raw_dps[dp_num] = val
            code = dp_map.get(dp_num)
            if code:
                self.status[code] = val

    def _dp_to_code_map(self) -> dict[int, str]:
        if self.dp_map:
            return {dp_id: code for code, dp_id in self.dp_map.items()}
        if self.category in ("cz", "pc", "tdq", "kg"):
            return dict(PLUG_DP_TO_CODE)
        if self.category in ("dj", "dd", "xdd"):
            return dict(LIGHT_DP_TO_CODE)
        if self.category in ("cl", "mc"):
            return dict(COVER_DP_TO_CODE)
        inv: dict[int, str] = {}
        for code, dp_id in CODE_TO_DEFAULT_DP.items():
            if code in self.status:
                inv[dp_id] = code
        return inv

    def resolve_dp_id(self, code: str) -> int | None:
        """Resolve o ID numérico do DP local correspondente a um `code` da Tuya."""
        if code in self.dp_map:
            return self.dp_map[code]
        if code.isdigit():
            return int(code)
        dp_map = self._dp_to_code_map()
        for dp_id, mapped_code in dp_map.items():
            if mapped_code == code:
                return dp_id
        return CODE_TO_DEFAULT_DP.get(code)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.device_id,
            "name": self.name,
            "category": self.category,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "model": self.model,
            "uuid": self.uuid,
            "online": self.online,
            "ip": self.ip_wan,
            "local_ip": self.local_ip,
            "local_version": self.local_version,
            "local_key": self.local_key,
            "sub": self.sub,
            "node_id": self.node_id,
            "owner_id": self.owner_id,
            "uid": self.uid,
            "icon": self.icon,
            "status": self.status,
            "dp_map": self.dp_map,
        }

    @classmethod
    def from_api(cls, raw: dict[str, Any], lan_info: dict[str, Any] | None = None) -> MwTuyaDevice:
        status_dict: dict[str, Any] = {}
        raw_status = raw.get("status")
        if isinstance(raw_status, list):
            for item in raw_status:
                if isinstance(item, dict) and "code" in item:
                    status_dict[str(item["code"])] = item.get("value")
        elif isinstance(raw_status, dict):
            status_dict = dict(raw_status)

        dev_id = str(raw.get("id") or raw.get("device_id") or "")
        lan = lan_info or {}
        default_ip, default_ver = DEFAULT_LOCAL_HOSTS.get(dev_id, ("", "3.3"))
        local_ip = str(lan.get("ip") or raw.get("local_ip") or default_ip or "")
        local_version = str(lan.get("version") or raw.get("local_version") or default_ver or "3.3")

        return cls(
            device_id=dev_id,
            name=str(raw.get("name") or dev_id).strip(),
            category=str(raw.get("category") or ""),
            product_id=str(raw.get("product_id") or ""),
            product_name=str(raw.get("product_name") or ""),
            model=str(raw.get("model") or "").strip(),
            uuid=str(raw.get("uuid") or ""),
            online=bool(raw.get("online", False)),
            ip_wan=str(raw.get("ip") or ""),
            local_ip=local_ip,
            local_version=local_version,
            local_key=str(raw.get("local_key") or ""),
            sub=bool(raw.get("sub", False)),
            node_id=str(raw.get("node_id") or ""),
            owner_id=str(raw.get("owner_id") or ""),
            uid=str(raw.get("uid") or ""),
            icon=str(raw.get("icon") or ""),
            status=status_dict,
        )


def infer_entity_specs(device: MwTuyaDevice) -> list[EntitySpec]:
    """Infere as entidades do Home Assistant a partir da categoria e dos DPs reais do aparelho."""
    specs: list[EntitySpec] = []
    status = device.status
    cat = device.category

    # 1. Switches principais (tomadas, réguas, interruptores)
    switch_codes = [
        k
        for k in sorted(status.keys())
        if (k == "switch" or k.startswith("switch_"))
        and k not in ("switch_led", "switch_spray", "switch_inching")
        and isinstance(status.get(k), bool)
    ]
    if not switch_codes and cat in ("cz", "pc", "tdq", "kg", "dlq"):
        switch_codes = ["switch_1"]

    # Em purificador/umidificador/climatizador, `switch` pertence à plataforma principal
    if cat in ("kj", "fs", "jsq", "kt", "wk") and "switch" in switch_codes:
        switch_codes.remove("switch")

    multi_switch = len(switch_codes) > 1
    for code in switch_codes:
        custom = device.custom_names.get(code)
        if custom:
            label = custom
        else:
            suffix = code.removeprefix("switch_").upper() if code != "switch" else ""
            label = f"Tomada {suffix}" if (multi_switch and suffix) else "Tomada"
            if cat in ("kg", "tdq", "dlq"):
                label = f"Interruptor {suffix}" if (multi_switch and suffix) else "Interruptor"
        specs.append(
            EntitySpec(
                platform="switch",
                code=code,
                name=label,
                dp_id=device.resolve_dp_id(code),
            )
        )

    # Switches de configuração / recursos extras (câmeras, purificadores, umidificadores, presença)
    aux_switches: list[tuple[str, str]] = [
        ("child_lock", "Trava Infantil"),
        ("Child_Lock", "Trava Infantil"),
        ("lock", "Trava Infantil"),
        ("basic_indicator", "LED Indicador"),
        ("indicator", "LED Indicador"),
        ("basic_private", "Modo Privacidade"),
        ("basic_osd", "Marca d'Água de Horário"),
        ("basic_flip", "Inverter Imagem"),
        ("motion_switch", "Alarme de Movimento"),
        ("record_switch", "Gravação em Cartão SD"),
        ("siren_switch", "Sirene"),
        ("sleep", "Modo Noturno"),
        ("mute", "Silenciar"),
    ]
    for aux_code, aux_label in aux_switches:
        if aux_code in status and isinstance(status[aux_code], bool):
            specs.append(
                EntitySpec(
                    platform="switch",
                    code=aux_code,
                    name=aux_label,
                    dp_id=device.resolve_dp_id(aux_code),
                    entity_category="config",
                )
            )

    # 2. Lâmpadas e Fitas LED (dj, dd, xdd ou presença de switch_led)
    if cat in ("dj", "dd", "xdd") or "switch_led" in status:
        light_code = "switch_led" if "switch_led" in status else "switch"
        specs.append(
            EntitySpec(
                platform="light",
                code=light_code,
                name="Luz",
                dp_id=device.resolve_dp_id(light_code),
            )
        )

    # 3. Cortinas e Motores de Janela (cl, mc)
    if cat in ("cl", "mc") or "percent_control" in status or "control" in status:
        cover_code = "percent_control" if "percent_control" in status else "control"
        specs.append(
            EntitySpec(
                platform="cover",
                code=cover_code,
                name="Cortina" if cat == "cl" else "Abertura",
                dp_id=device.resolve_dp_id(cover_code),
                device_class="curtain" if cat == "cl" else "window",
            )
        )

    # 4. Purificadores de Ar e Ventiladores (kj, fs)
    if cat in ("kj", "fs") and ("switch" in status or "fan_speed_enum" in status):
        specs.append(
            EntitySpec(
                platform="fan",
                code="switch",
                name="Purificador de Ar" if cat == "kj" else "Ventilador",
                dp_id=device.resolve_dp_id("switch") or 1,
            )
        )

    # 5. Umidificadores (jsq)
    if cat == "jsq":
        hum_code = "switch_spray" if "switch_spray" in status else "switch"
        specs.append(
            EntitySpec(
                platform="humidifier",
                code=hum_code,
                name="Umidificador",
                dp_id=device.resolve_dp_id(hum_code) or 1,
            )
        )

    # 6. Ar-Condicionado / Climatização (kt, wk)
    if cat in ("kt", "wk") and ("temp_set" in status or "switch" in status):
        specs.append(
            EntitySpec(
                platform="climate",
                code="switch",
                name="Climatização",
                dp_id=device.resolve_dp_id("switch") or 1,
            )
        )

    # 7. Selects (Estado do Relé, Modo do LED, Modo de Gravação, Nível de Névoa)
    select_defs: list[tuple[str, str, list[str]]] = [
        (
            "relay_status",
            "Estado Pós-Queda",
            ["off", "on", "memory", "power_off", "power_on", "last"],
        ),
        ("light_mode", "Modo do LED Indicador", ["relay", "pos", "none", "off", "on"]),
        ("record_mode", "Modo de Gravação", ["1", "2"]),
        ("level", "Nível de Névoa", ["level_1", "level_2", "level_3"]),
        ("countdown_set", "Timer Programado", ["cancel", "1h", "2h", "3h", "4h", "5h", "6h"]),
    ]
    for sel_code, sel_label, default_opts in select_defs:
        if sel_code in status and isinstance(status[sel_code], str):
            cur_val = str(status[sel_code])
            opts = list(default_opts)
            if cur_val and cur_val not in opts:
                opts.append(cur_val)
            specs.append(
                EntitySpec(
                    platform="select",
                    code=sel_code,
                    name=sel_label,
                    dp_id=device.resolve_dp_id(sel_code),
                    options=opts,
                    entity_category="config",
                )
            )

    # 8. Numbers (Timers / Countdowns e Sensibilidade de Presença mmWave)
    number_defs: list[tuple[str, str, str | None, float, float, float]] = [
        ("countdown_1", "Timer Canal 1", "s", 0.0, 86400.0, 60.0),
        ("countdown_2", "Timer Canal 2", "s", 0.0, 86400.0, 60.0),
        ("countdown_3", "Timer Canal 3", "s", 0.0, 86400.0, 60.0),
        ("countdown_4", "Timer Canal 4", "s", 0.0, 86400.0, 60.0),
        ("countdown_5", "Timer Canal 5", "s", 0.0, 86400.0, 60.0),
        ("countdown_6", "Timer Canal 6", "s", 0.0, 86400.0, 60.0),
        ("countdown", "Timer", "s", 0.0, 86400.0, 60.0),
        ("far_detection", "Distância Máxima Detecção", "cm", 0.0, 1000.0, 15.0),
        ("near_detection", "Distância Mínima Detecção", "cm", 0.0, 1000.0, 15.0),
        ("presence_time", "Tempo de Retenção", "s", 0.0, 3600.0, 1.0),
        ("no_one_time", "Atraso Sem Presença", "s", 0.0, 3600.0, 1.0),
        ("motion_sensitivity_value", "Sensibilidade em Movimento", None, 0.0, 10.0, 1.0),
        ("motionless_sensitivity", "Sensibilidade Estático", None, 0.0, 10.0, 1.0),
    ]
    for num_code, num_label, unit, min_v, max_v, step_v in number_defs:
        if num_code in status and isinstance(status[num_code], (int, float)):
            specs.append(
                EntitySpec(
                    platform="number",
                    code=num_code,
                    name=num_label,
                    dp_id=device.resolve_dp_id(num_code),
                    unit=unit,
                    min_value=min_v,
                    max_value=max_v,
                    step=step_v,
                    entity_category="config",
                )
            )

    # 9. Buttons (Reset de Filtro / Medidor)
    button_defs: list[tuple[str, str]] = [
        ("filter_reset", "Resetar Filtro"),
        ("reset_add_ele", "Zerar Medidor de Energia"),
        ("restart", "Reiniciar Dispositivo"),
    ]
    for btn_code, btn_label in button_defs:
        if btn_code in status:
            specs.append(
                EntitySpec(
                    platform="button",
                    code=btn_code,
                    name=btn_label,
                    dp_id=device.resolve_dp_id(btn_code),
                    entity_category="config",
                )
            )

    # 10. Sensores de Energia, Ambiente e Bateria
    sensor_defs: list[tuple[str, str, str | None, str | None, float, str | None]] = [
        ("cur_current", "Corrente", "current", "mA", 1.0, "measurement"),
        ("cur_power", "Potência", "power", "W", 0.1, "measurement"),
        ("cur_voltage", "Voltagem", "voltage", "V", 0.1, "measurement"),
        ("add_ele", "Energia Acumulada", "energy", "kWh", 0.001, "total_increasing"),
        ("va_temperature", "Temperatura", "temperature", "°C", 0.1, "measurement"),
        ("temp_current", "Temperatura", "temperature", "°C", 1.0, "measurement"),
        ("va_humidity", "Umidade", "humidity", "%", 1.0, "measurement"),
        ("humidity_value", "Umidade", "humidity", "%", 1.0, "measurement"),
        ("humidity_current", "Umidade Atual", "humidity", "%", 1.0, "measurement"),
        ("bright_value", "Luminosidade", "illuminance", "lx", 1.0, "measurement"),
        ("illuminance_value", "Luminosidade", "illuminance", "lx", 1.0, "measurement"),
        ("dis_current", "Distância Alvo", "distance", "cm", 1.0, "measurement"),
        ("pm25_value", "PM2.5", "pm25", "µg/m³", 1.0, "measurement"),
        ("co2_value", "CO₂", "carbon_dioxide", "ppm", 1.0, "measurement"),
        ("voc_value", "TVOC", "volatile_organic_compounds", "µg/m³", 1.0, "measurement"),
        ("ch2o_value", "Formaldeído", None, "mg/m³", 0.01, "measurement"),
        ("battery_percentage", "Bateria", "battery", "%", 1.0, "measurement"),
        ("va_battery", "Bateria", "battery", "%", 1.0, "measurement"),
        ("filter_life", "Vida Útil do Filtro", None, "%", 1.0, "measurement"),
        ("filter_days", "Dias Restantes do Filtro", None, "d", 1.0, "measurement"),
    ]
    for code, label, dclass, unit, scale, sclass in sensor_defs:
        if code == "bright_value" and cat in ("dj", "dd", "xdd"):
            continue
        if code in status and isinstance(status[code], (int, float)):
            actual_scale = scale
            if dclass == "temperature" and scale == 1.0 and float(status[code]) > 100:
                actual_scale = 0.1
            specs.append(
                EntitySpec(
                    platform="sensor",
                    code=code,
                    name=label,
                    dp_id=device.resolve_dp_id(code),
                    device_class=dclass,
                    unit=unit,
                    scale=actual_scale,
                    state_class=sclass,
                )
            )

    # 11. Binary Sensors (Presença, Movimento, Porta/Janela, SOS, Vibração)
    binary_defs: list[tuple[str, str, str, Any]] = [
        ("doorcontact_state", "Contato", "door", True),
        ("pir", "Movimento", "motion", "pir"),
        ("presence_state", "Presença", "occupancy", "presence"),
        ("sos_state", "Emergência SOS", "safety", True),
        ("shock_state", "Vibração", "vibration", "vibration"),
        ("watersensor_state", "Vazamento de Água", "moisture", "alarm"),
    ]
    for code, label, dclass, active_val in binary_defs:
        if code in status:
            specs.append(
                EntitySpec(
                    platform="binary_sensor",
                    code=code,
                    name=label,
                    dp_id=device.resolve_dp_id(code),
                    device_class=dclass,
                    options=[str(active_val)],
                )
            )

    return specs
