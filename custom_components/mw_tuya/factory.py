"""Fábrica de entidades guiada pelo Thing Model (com fallback pelo status observado).

Regras:
1. A categoria define a entidade principal (light/fan/cover/humidifier/climate/switch).
2. Os DPs restantes viram entidades genéricas pelo tipo (`bool`/`enum`/`value`).
3. Entidades de configuração/diagnóstico nascem desabilitadas — evita a explosão
   de entidades; a migração reabilita as que estavam ativas na integração antiga.
"""

from __future__ import annotations

from typing import Any

from .catalog import (
    BINARY_CLASSES,
    BUTTON_CODES,
    CLIMATE_CATS,
    COVER_CATS,
    ENUM_SENSOR_ENABLED,
    FAN_CATS,
    HUMIDIFIER_CATS,
    LIGHT_CATS,
    SENSOR_CLASSES,
    SKIP_CATS,
    SKIP_CODES,
    label_for,
)
from .dpspec import DpSpec
from .models import EntitySpec, MwTuyaDevice


def _type_of(dev: MwTuyaDevice, code: str) -> str:
    spec = dev.spec(code)
    if spec:
        return spec.type
    val = dev.status.get(code)
    if isinstance(val, bool):
        return "bool"
    if isinstance(val, (int, float)):
        return "value"
    if isinstance(val, str):
        return "enum" if val and not val.startswith(("{", "[")) and len(val) < 32 else "string"
    return "raw"


def _access_of(dev: MwTuyaDevice, code: str) -> str:
    spec = dev.spec(code)
    if spec:
        return spec.access
    return "rw" if _type_of(dev, code) == "bool" else "ro"


def _all_codes(dev: MwTuyaDevice) -> list[str]:
    codes = list(dev.specs) if dev.specs else []
    for code in dev.status:
        if code not in codes:
            codes.append(code)
    return codes


def _mk(dev: MwTuyaDevice, platform: str, code: str, name: str | None, **kw: Any) -> EntitySpec:
    spec: DpSpec | None = dev.spec(code)
    return EntitySpec(
        platform=platform,
        code=code,
        name=name,
        dp_id=dev.resolve_dp_id(code),
        dp=spec,
        **kw,
    )


# --------------------------------------------------------------------------- principais
def _light(dev: MwTuyaDevice, used: set[str]) -> list[EntitySpec]:
    switches = [c for c in _all_codes(dev) if c == "switch_led" or c.startswith("switch_led_")]
    if not switches and dev.has("switch"):
        switches = ["switch"]
    out: list[EntitySpec] = []
    multi = len(switches) > 1
    for sw in sorted(switches):
        suffix = sw.removeprefix("switch_led").lstrip("_")

        def pick(*cs: str, _sfx: str = suffix) -> str | None:
            return dev.first(*[f"{c}_{_sfx}" if _sfx else c for c in cs])

        extra = {
            "switch": sw,
            "bright": pick("bright_value_v2", "bright_value"),
            "temp": pick("temp_value_v2", "temp_value"),
            "colour": pick("colour_data_v2", "colour_data"),
            "mode": pick("work_mode"),
        }
        used.update(c for c in extra.values() if c)
        name = label_for(sw, dev.custom_names) if multi else None
        out.append(_mk(dev, "light", sw, name, extra=extra))
    return out


def _fan(dev: MwTuyaDevice, used: set[str]) -> list[EntitySpec]:
    sw = dev.first("switch", "switch_fan", "fan_switch")
    if not sw:
        return []
    extra = {
        "switch": sw,
        "speed": dev.first("speed", "fan_speed_enum", "fan_speed_percent", "fan_speed"),
        "preset": dev.first("mode", "fan_mode"),
        "direction": dev.first("fan_direction"),
        "oscillate": dev.first("switch_horizontal", "switch_vertical"),
    }
    used.update(c for c in extra.values() if c)
    return [_mk(dev, "fan", sw, None, extra=extra)]


def _cover(dev: MwTuyaDevice, used: set[str]) -> list[EntitySpec]:
    control = dev.first("control", "wd_control", "mach_operate", "control_1")
    position = dev.first("percent_control", "wd_percent_control", "position", "percent_control_1")
    if not control and not position:
        return []
    extra = {
        "control": control,
        "position": position,
        "state": dev.first("percent_state", "percent_state_1"),
        "window_state": dev.first("window_state"),
    }
    used.update(c for c in (control, position, extra["state"]) if c)
    dclass = "window" if dev.category == "mc" else "curtain"
    return [_mk(dev, "cover", control or position, None, device_class=dclass, extra=extra)]


def _humidifier(dev: MwTuyaDevice, used: set[str]) -> list[EntitySpec]:
    sw = dev.first("switch", "switch_spray")
    if not sw:
        return []
    extra = {
        "switch": sw,
        "mode": dev.first("mode", "work_mode", "level"),
        "target": dev.first("humidity_set", "dehumidify_set_value"),
        "current": dev.first("humidity_current", "humidity_indoor"),
    }
    used.update(c for c in extra.values() if c)
    return [_mk(dev, "humidifier", sw, None, extra=extra)]


def _climate(dev: MwTuyaDevice, used: set[str]) -> list[EntitySpec]:
    sw = dev.first("switch")
    if not sw:
        return []
    extra = {
        "switch": sw,
        "target": dev.first("temp_set", "temp_set_f"),
        "current": dev.first("temp_current", "temp_indoor"),
        "mode": dev.first("mode"),
        "fan": dev.first("windspeed", "fan_speed_enum"),
    }
    used.update(c for c in extra.values() if c)
    return [_mk(dev, "climate", sw, None, extra=extra)]


def _switches(dev: MwTuyaDevice, used: set[str]) -> list[EntitySpec]:
    codes = [
        c
        for c in _all_codes(dev)
        if (
            c == "switch"
            or (c.startswith("switch_") and c[7:].isdigit())
            or c.startswith("switch_usb")
        )
        and c not in used
        and _type_of(dev, c) == "bool"
    ]
    out: list[EntitySpec] = []
    multi = len(codes) > 1
    for code in sorted(codes):
        used.add(code)
        if code in dev.custom_names:
            name: str | None = dev.custom_names[code]
        elif multi:
            name = (
                f"Canal {code.removeprefix('switch_').upper()}" if code != "switch" else "Principal"
            )
        else:
            name = None
        out.append(_mk(dev, "switch", code, name))
    return out


# --------------------------------------------------------------------------- genéricas
def _generic(dev: MwTuyaDevice, code: str) -> EntitySpec | None:
    typ = _type_of(dev, code)
    access = _access_of(dev, code)
    spec = dev.spec(code)
    name = label_for(code, dev.custom_names)
    readable, writable = "r" in access, "w" in access

    if code in BUTTON_CODES and writable:
        return _mk(dev, "button", code, name, entity_category="config", enabled_default=False)

    if code in BINARY_CLASSES and readable and not writable:
        dclass, on_values = BINARY_CLASSES[code]
        return _mk(dev, "binary_sensor", code, name, device_class=dclass, options=sorted(on_values))

    if typ == "bool":
        if writable:
            return _mk(dev, "switch", code, name, entity_category="config", enabled_default=False)
        return _mk(dev, "binary_sensor", code, name, options=["true"], enabled_default=False)

    if typ == "enum":
        opts = list(spec.range) if spec and spec.range else []
        cur = dev.status.get(code)
        if isinstance(cur, str) and cur and cur not in opts:
            opts.append(cur)
        if writable and readable and opts:
            return _mk(
                dev,
                "select",
                code,
                name,
                options=opts,
                entity_category="config",
                enabled_default=False,
            )
        if readable:
            return _mk(
                dev,
                "sensor",
                code,
                name,
                device_class="enum",
                options=opts,
                enabled_default=code in ENUM_SENSOR_ENABLED,
                entity_category=None if code in ENUM_SENSOR_ENABLED else "diagnostic",
            )
        return None

    if typ == "value":
        unit = spec.unit if spec else None
        if writable and readable:
            return _mk(
                dev,
                "number",
                code,
                name,
                unit=unit,
                min_value=spec.ha_min if spec else 0,
                max_value=spec.ha_max if spec else 100,
                step=spec.ha_step if spec else 1,
                entity_category="config",
                enabled_default=False,
            )
        if readable:
            dclass, dunit, sclass, enabled = SENSOR_CLASSES.get(
                code, (None, None, "measurement", False)
            )
            unit = unit or dunit
            if dclass == "volatile_organic_compounds" and unit in ("ppm", "ppb"):
                dclass = "volatile_organic_compounds_parts"
            if dclass == "illuminance" and unit not in (None, "lx"):
                dclass, unit = None, unit
            return _mk(
                dev,
                "sensor",
                code,
                name,
                device_class=dclass,
                unit=unit,
                state_class=sclass,
                enabled_default=enabled,
                entity_category=None if enabled else "diagnostic",
            )
    return None


def build_entity_specs(dev: MwTuyaDevice) -> list[EntitySpec]:
    """Gera as entidades do dispositivo."""
    if dev.category in SKIP_CATS:
        return []
    used: set[str] = set()
    specs: list[EntitySpec] = []
    cat = dev.category

    if cat in LIGHT_CATS or (dev.has("switch_led") and cat not in FAN_CATS | HUMIDIFIER_CATS):
        specs += _light(dev, used)
    if cat in FAN_CATS:
        specs += _fan(dev, used)
    if cat in COVER_CATS or (not specs and dev.first("percent_control", "wd_control")):
        specs += _cover(dev, used)
    if cat in HUMIDIFIER_CATS:
        specs += _humidifier(dev, used)
    if cat in CLIMATE_CATS:
        specs += _climate(dev, used)
    specs += _switches(dev, used)

    for code in _all_codes(dev):
        if code in used or code in SKIP_CODES:
            continue
        if code == "bright_value" and cat in LIGHT_CATS:
            continue
        ent = _generic(dev, code)
        if ent:
            used.add(code)
            specs.append(ent)
    return specs
