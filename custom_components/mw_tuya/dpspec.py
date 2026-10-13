"""Especificação de DP (Thing Model v2.0) e codecs Local ⇄ Cloud.

O Thing Model (`/v2.0/cloud/thing/{id}/model`) descreve cada DP do aparelho:
`abilityId` (dp_id local), `code`, `accessMode` e `typeSpec` (tipo, faixa,
escala, passo, unidade, opções). É a fonte da verdade para gerar entidades com
escala/unidade corretas e para traduzir DPs locais (TCP 6668) em códigos Cloud.

O estado canônico guardado em `MwTuyaDevice.status` segue o formato da Cloud;
valores lidos localmente passam por `decode_local` e comandos locais por
`encode_local`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

UNIT_FIX: dict[str, str | None] = {
    "℃": "°C",
    "℉": "°F",
    "分钟": "min",
    "秒": "s",
    "小时": "h",
    "天": "d",
    "day": "d",
    "days": "d",
    "lux": "lx",
    "Lux": "lx",
    "kW.h": "kWh",
    "kW·h": "kWh",
    "kwh": "kWh",
    "KWH": "kWh",
    "mins": "min",
    "": None,
}


@dataclass(slots=True)
class DpSpec:
    """Descrição tipada de um DP Tuya."""

    code: str
    dp_id: int | None = None
    access: str = "rw"
    type: str = "raw"
    min: float = 0
    max: float = 0
    scale: int = 0
    step: float = 1
    unit: str | None = None
    range: list[str] = field(default_factory=list)
    label: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- acesso
    @property
    def readable(self) -> bool:
        return "r" in self.access

    @property
    def writable(self) -> bool:
        return "w" in self.access

    @property
    def factor(self) -> float:
        return 10 ** (-self.scale) if self.scale else 1.0

    # ---------------------------------------------------------------- valores
    def to_ha(self, raw: Any) -> Any:
        """Valor bruto Tuya → valor HA (aplica escala)."""
        if self.type != "value" or not isinstance(raw, (int, float)) or isinstance(raw, bool):
            return raw
        if not self.scale:
            return raw
        return round(raw * self.factor, self.scale)

    def from_ha(self, value: float) -> int:
        """Valor HA → bruto Tuya (desfaz escala, aplica passo e faixa)."""
        raw = round(float(value) / self.factor)
        step = int(self.step) or 1
        raw = round(raw / step) * step
        if self.max > self.min:
            raw = max(int(self.min), min(int(self.max), raw))
        return int(raw)

    @property
    def ha_min(self) -> float:
        return self.to_ha(self.min) if self.scale else self.min

    @property
    def ha_max(self) -> float:
        return self.to_ha(self.max) if self.scale else self.max

    @property
    def ha_step(self) -> float:
        return (self.step or 1) * self.factor

    # ---------------------------------------------------------------- serialização
    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "dp_id": self.dp_id,
            "access": self.access,
            "type": self.type,
            "min": self.min,
            "max": self.max,
            "scale": self.scale,
            "step": self.step,
            "unit": self.unit,
            "range": self.range,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DpSpec:
        return cls(**{k: data[k] for k in cls.__slots__ if k in data})  # type: ignore[attr-defined]

    @classmethod
    def from_thing_property(cls, prop: dict[str, Any]) -> DpSpec | None:
        code = str(prop.get("code") or "").strip()
        if not code:
            return None
        ts = prop.get("typeSpec") or {}
        dp_id = prop.get("abilityId")
        unit = ts.get("unit")
        unit = UNIT_FIX.get(unit, unit) if isinstance(unit, str) else None
        return cls(
            code=code,
            dp_id=int(dp_id) if isinstance(dp_id, (int, str)) and str(dp_id).isdigit() else None,
            access=str(prop.get("accessMode") or "rw"),
            type=str(ts.get("type") or "raw"),
            min=ts.get("min", 0) or 0,
            max=ts.get("max", 0) or 0,
            scale=int(ts.get("scale", 0) or 0),
            step=ts.get("step", 1) or 1,
            unit=unit,
            range=[str(x) for x in ts.get("range") or []],
            label=[str(x) for x in ts.get("label") or []],
        )


def parse_thing_model(result: Any) -> dict[str, DpSpec]:
    """Converte a resposta de `/v2.0/cloud/thing/{id}/model` em `{code: DpSpec}`."""
    model: Any = result.get("model") if isinstance(result, dict) else None
    if isinstance(model, str):
        try:
            model = json.loads(model)
        except ValueError:
            return {}
    if not isinstance(model, dict):
        return {}
    specs: dict[str, DpSpec] = {}
    for service in model.get("services") or []:
        for prop in service.get("properties") or []:
            spec = DpSpec.from_thing_property(prop)
            if spec:
                specs[spec.code] = spec
    return specs


# --------------------------------------------------------------------------- cor
def is_colour_code(code: str) -> bool:
    return code in ("colour_data", "colour_data_v2", "colour_data_raw")


def parse_hsv(value: Any) -> dict[str, int] | None:
    """Lê HSV no formato Cloud (`{"h":..,"s":..,"v":..}` em str/dict) ou hex local."""
    if isinstance(value, dict):
        data = value
    elif isinstance(value, str):
        txt = value.strip()
        if txt.startswith("{"):
            try:
                data = json.loads(txt)
            except ValueError:
                return None
        else:
            return decode_hsv_hex(txt)
    else:
        return None
    try:
        return {"h": int(data["h"]), "s": int(data["s"]), "v": int(data["v"])}
    except (KeyError, TypeError, ValueError):
        return None


def decode_hsv_hex(txt: str) -> dict[str, int] | None:
    """Hex local → HSV. v2: `hhhhssssvvvv` (0-1000). v1: `rrggbbhhhhssvv` (0-255)."""
    try:
        if len(txt) == 12:
            return {"h": int(txt[0:4], 16), "s": int(txt[4:8], 16), "v": int(txt[8:12], 16)}
        if len(txt) == 14:
            return {"h": int(txt[6:10], 16), "s": int(txt[10:12], 16), "v": int(txt[12:14], 16)}
    except ValueError:
        return None
    return None


def encode_hsv_hex(hsv: dict[str, int], v2: bool) -> str:
    h, s, v = int(hsv["h"]), int(hsv["s"]), int(hsv["v"])
    if v2:
        return f"{h:04x}{s:04x}{v:04x}"
    # v1 também carrega RGB redundante
    import colorsys

    r, g, b = colorsys.hsv_to_rgb(h / 360.0, s / 255.0, v / 255.0)
    return f"{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}{h:04x}{s:02x}{v:02x}"


def decode_local(code: str, value: Any) -> Any:
    """Valor lido via TCP local → formato canônico (Cloud)."""
    if is_colour_code(code) and isinstance(value, str) and not value.strip().startswith("{"):
        hsv = decode_hsv_hex(value.strip())
        if hsv is not None:
            return json.dumps(hsv, separators=(",", ":"))
    return value


def encode_local(code: str, value: Any, local_hex_len: int | None = None) -> Any:
    """Valor canônico (Cloud) → formato aceito pelo DP local."""
    if is_colour_code(code):
        hsv = parse_hsv(value)
        if hsv is not None:
            v2 = code == "colour_data_v2" or local_hex_len == 12 or max(hsv["s"], hsv["v"]) > 255
            return encode_hsv_hex(hsv, v2=v2)
    return value
