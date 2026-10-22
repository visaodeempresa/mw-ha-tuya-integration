"""Modelos de domínio (Device/Scene) da MW Tuya Integration.

A geração de entidades fica em `factory.py`; a tipagem de DPs em `dpspec.py`.
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
    DP_ALIASES,
    LIGHT_DP_TO_CODE,
    PLUG_DP_TO_CODE,
)
from .dpspec import DpSpec, decode_local, is_colour_code


@dataclass(slots=True)
class EntitySpec:
    """Especificação de uma entidade do Home Assistant derivada dos DPs do dispositivo."""

    platform: str
    code: str
    name: str | None
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
    dp: DpSpec | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    enabled_default: bool = True
    icon: str | None = None


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
    specs: dict[str, DpSpec] = field(default_factory=dict)
    local_hex_len: dict[str, int] = field(default_factory=dict)

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, f"Dispositivo ({self.category or 'outro'})")

    @property
    def has_valid_local_key(self) -> bool:
        if not self.local_key or len(self.local_key) < 16:
            return False
        # Máscaras da Tuya usam strings com asteriscos (ex: "****************").
        # Chaves válidas geradas pela Tuya podem conter '*', o que é legítimo.
        return not (self.local_key.count("*") >= 8 or set(self.local_key) == {"*"})

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

    # ------------------------------------------------------------------ specs
    def spec(self, code: str) -> DpSpec | None:
        if code in self.specs:
            return self.specs[code]
        for alias in DP_ALIASES.get(code, ()):
            if alias in self.specs:
                return self.specs[alias]
        return None

    def has(self, code: str) -> bool:
        """O DP existe no aparelho (pelo Thing Model ou pelo status observado)."""
        if code in self.specs or code in self.status:
            return True
        for alias in DP_ALIASES.get(code, ()):
            if alias in self.specs or alias in self.status:
                return True
        return False

    def first(self, *codes: str) -> str | None:
        for code in codes:
            if self.has(code):
                return code
        return None

    def apply_thing_model(self, specs: dict[str, DpSpec]) -> None:
        """Aplica o Thing Model v2.0 (fonte da verdade de dp_id, tipo e escala)."""
        if not specs:
            return
        self.specs = dict(specs)
        for code, spec in specs.items():
            if spec.dp_id is not None:
                self.dp_map[code] = spec.dp_id
                for alias in DP_ALIASES.get(code, ()):
                    self.dp_map.setdefault(alias, spec.dp_id)

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
            if not code:
                continue
            if is_colour_code(code) and isinstance(val, str) and not val.startswith("{"):
                hex_len = len(val.strip())
                self.local_hex_len[code] = hex_len
                for alias in DP_ALIASES.get(code, ()):
                    self.local_hex_len[alias] = hex_len
            decoded = decode_local(code, val)
            self.status[code] = decoded
            for alias in DP_ALIASES.get(code, ()):
                self.status[alias] = decoded

    def _dp_to_code_map(self) -> dict[int, str]:
        if self.dp_map:
            return {dp_id: code for code, dp_id in self.dp_map.items()}
        if self.category in ("cz", "pc", "tdq", "kg"):
            return dict(PLUG_DP_TO_CODE)
        if self.category in ("dj", "dd", "xdd"):
            return dict(LIGHT_DP_TO_CODE)
        if self.category in ("cl", "mc"):
            return dict(COVER_DP_TO_CODE)
        return {}

    def resolve_dp_id(self, code: str) -> int | None:
        """Resolve o ID do DP local em dp_map, aliases, mapa por categoria e defaults."""
        if code in self.dp_map:
            return self.dp_map[code]
        for alias in DP_ALIASES.get(code, ()):
            if alias in self.dp_map:
                return self.dp_map[alias]
        if self.specs:
            # Quando há modelo definido, só resolve códigos pertencentes ao modelo/categoria
            if code in self.specs or any(a in self.specs for a in DP_ALIASES.get(code, ())):
                for dp_id, mapped_code in self._dp_to_code_map().items():
                    if mapped_code == code or mapped_code in DP_ALIASES.get(code, ()):
                        return dp_id
            return None
        for dp_id, mapped_code in self._dp_to_code_map().items():
            if mapped_code == code or mapped_code in DP_ALIASES.get(code, ()):
                return dp_id
        if code in CODE_TO_DEFAULT_DP:
            return CODE_TO_DEFAULT_DP[code]
        for alias in DP_ALIASES.get(code, ()):
            if alias in CODE_TO_DEFAULT_DP:
                return CODE_TO_DEFAULT_DP[alias]
        return None

    # ------------------------------------------------------------------ serialização
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
            "specs": {k: v.to_dict() for k, v in self.specs.items()},
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

        dev = cls(
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
        specs = raw.get("specs")
        if isinstance(specs, dict):
            dev.apply_thing_model({k: DpSpec.from_dict(v) for k, v in specs.items()})
        return dev


def infer_entity_specs(device: MwTuyaDevice) -> list[EntitySpec]:
    """Compat: delega para `factory.build_entity_specs`."""
    from .factory import build_entity_specs

    return build_entity_specs(device)
