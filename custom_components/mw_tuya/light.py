"""Plataforma `light`: liga/desliga, brilho, temperatura de cor e cor HS (v1 e v2)."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MwTuyaCoordinator
from .dpspec import parse_hsv
from .entity import MwTuyaEntity
from .models import infer_entity_specs

KELVIN_WARM = 2700
KELVIN_COLD = 6500


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MwTuyaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        MwTuyaLight(coordinator, dev, spec)
        for dev in coordinator.active_devices
        for spec in infer_entity_specs(dev)
        if spec.platform == "light"
    )


def _range(spec, default_min: int, default_max: int) -> tuple[int, int]:
    if spec and spec.max > spec.min:
        return int(spec.min), int(spec.max)
    return default_min, default_max


class MwTuyaLight(MwTuyaEntity, LightEntity):
    """Lâmpada / fita LED híbrida Local + Cloud."""

    _attr_min_color_temp_kelvin = KELVIN_WARM
    _attr_max_color_temp_kelvin = KELVIN_COLD

    def __init__(self, coordinator, device, spec) -> None:
        super().__init__(coordinator, device, spec)
        ex = spec.extra
        self._c_switch: str = ex.get("switch") or spec.code
        self._c_bright: str | None = ex.get("bright")
        self._c_temp: str | None = ex.get("temp")
        self._c_colour: str | None = ex.get("colour")
        self._c_mode: str | None = ex.get("mode")
        modes: set[ColorMode] = set()
        if self._c_colour:
            modes.add(ColorMode.HS)
        if self._c_temp:
            modes.add(ColorMode.COLOR_TEMP)
        if not modes:
            modes.add(ColorMode.BRIGHTNESS if self._c_bright else ColorMode.ONOFF)
        self._attr_supported_color_modes = modes

    # ------------------------------------------------------------------ helpers
    def _dp(self, code: str | None):
        dev = self.device_obj
        return dev.spec(code) if dev and code else None

    def _bright_range(self) -> tuple[int, int]:
        default_max = 1000 if (self._c_bright or "").endswith("_v2") else 255
        return _range(self._dp(self._c_bright), 10 if default_max == 1000 else 25, default_max)

    def _temp_range(self) -> tuple[int, int]:
        default_max = 1000 if (self._c_temp or "").endswith("_v2") else 255
        return _range(self._dp(self._c_temp), 0, default_max)

    def _hsv(self) -> dict[str, int] | None:
        return parse_hsv(self.status_of(self._c_colour))

    def _hsv_max(self) -> int:
        if self._c_colour == "colour_data_v2":
            return 1000
        hsv = self._hsv()
        if hsv and max(hsv["s"], hsv["v"]) > 255:
            return 1000
        return 255

    def _in_colour(self) -> bool:
        if not self._c_colour:
            return False
        if self._c_mode:
            return self.status_of(self._c_mode) == "colour"
        return not (self._c_bright or self._c_temp)

    # ------------------------------------------------------------------ estado
    @property
    def is_on(self) -> bool | None:
        val = self.status_of(self._c_switch)
        return None if val is None else bool(val)

    @property
    def color_mode(self) -> ColorMode:
        if self._in_colour():
            return ColorMode.HS
        if self._c_temp:
            return ColorMode.COLOR_TEMP
        if ColorMode.HS in self._attr_supported_color_modes:
            return ColorMode.HS
        return next(iter(self._attr_supported_color_modes))

    @property
    def brightness(self) -> int | None:
        if self._in_colour():
            hsv = self._hsv()
            if not hsv:
                return None
            return max(1, min(255, round(hsv["v"] / self._hsv_max() * 255)))
        raw = self.status_of(self._c_bright)
        if not isinstance(raw, (int, float)):
            return None
        lo, hi = self._bright_range()
        return max(1, min(255, round((raw - lo) / max(1, hi - lo) * 254 + 1)))

    @property
    def color_temp_kelvin(self) -> int | None:
        raw = self.status_of(self._c_temp)
        if not isinstance(raw, (int, float)):
            return None
        lo, hi = self._temp_range()
        frac = (raw - lo) / max(1, hi - lo)
        return round(KELVIN_WARM + frac * (KELVIN_COLD - KELVIN_WARM))

    @property
    def hs_color(self) -> tuple[float, float] | None:
        hsv = self._hsv()
        if not hsv:
            return None
        return float(hsv["h"]), round(hsv["s"] / self._hsv_max() * 100, 1)

    # ------------------------------------------------------------------ comandos
    async def async_turn_on(self, **kwargs: Any) -> None:
        cmds: dict[str, Any] = {self._c_switch: True}
        hs = kwargs.get(ATTR_HS_COLOR)
        kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
        bright = kwargs.get(ATTR_BRIGHTNESS)

        if hs is not None and self._c_colour:
            mx = self._hsv_max()
            cur = self._hsv() or {"v": mx}
            v = round(bright / 255 * mx) if bright is not None else (cur.get("v") or mx)
            cmds[self._c_colour] = json.dumps(
                {"h": round(hs[0]), "s": round(hs[1] / 100 * mx), "v": max(1, v)},
                separators=(",", ":"),
            )
            if self._c_mode:
                cmds[self._c_mode] = "colour"
        elif kelvin is not None and self._c_temp:
            lo, hi = self._temp_range()
            frac = (min(KELVIN_COLD, max(KELVIN_WARM, kelvin)) - KELVIN_WARM) / (
                KELVIN_COLD - KELVIN_WARM
            )
            cmds[self._c_temp] = round(lo + frac * (hi - lo))
            if self._c_mode:
                cmds[self._c_mode] = "white"
            if bright is not None and self._c_bright:
                lo_b, hi_b = self._bright_range()
                cmds[self._c_bright] = round(lo_b + (bright - 1) / 254 * (hi_b - lo_b))
        elif bright is not None:
            if self._in_colour():
                mx = self._hsv_max()
                cur = self._hsv() or {"h": 0, "s": 0}
                cmds[self._c_colour] = json.dumps(  # type: ignore[index]
                    {"h": cur["h"], "s": cur["s"], "v": max(1, round(bright / 255 * mx))},
                    separators=(",", ":"),
                )
            elif self._c_bright:
                lo, hi = self._bright_range()
                cmds[self._c_bright] = round(lo + (bright - 1) / 254 * (hi - lo))
                if self._c_mode and self.status_of(self._c_mode) not in ("white", None):
                    cmds[self._c_mode] = "white"
        await self.send(cmds)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.send({self._c_switch: False})
