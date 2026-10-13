"""Plataforma `light` da MW Tuya Integration (Local TCP 6668 + Fallback Cloud)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MwTuyaCoordinator
from .entity import MwTuyaEntity
from .models import infer_entity_specs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MwTuyaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[MwTuyaLight] = []
    for dev in coordinator.active_devices:
        for spec in infer_entity_specs(dev):
            if spec.platform == "light":
                entities.append(MwTuyaLight(coordinator, dev, spec))
    async_add_entities(entities)


class MwTuyaLight(MwTuyaEntity, LightEntity):
    """Lâmpada / Fita LED híbrida Local + Cloud."""

    @property
    def _brightness_code(self) -> str | None:
        dev = self.device_obj
        if not dev:
            return None
        for candidate in ("bright_value_v2", "bright_value"):
            if candidate in dev.status:
                return candidate
        return None

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        if self._brightness_code:
            return {ColorMode.BRIGHTNESS}
        return {ColorMode.ONOFF}

    @property
    def color_mode(self) -> ColorMode:
        if self._brightness_code:
            return ColorMode.BRIGHTNESS
        return ColorMode.ONOFF

    @property
    def is_on(self) -> bool | None:
        val = self.dp_value
        if val is None:
            return None
        return bool(val)

    @property
    def brightness(self) -> int | None:
        dev = self.device_obj
        bcode = self._brightness_code
        if not dev or not bcode:
            return None
        raw = dev.status.get(bcode)
        if not isinstance(raw, (int, float)):
            return None
        max_scale = 1000.0 if bcode == "bright_value_v2" or raw > 255 else 255.0
        return max(1, min(255, round((float(raw) / max_scale) * 255)))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_device_command(
            self._device_id, self._spec.code, True, dp_id=self._spec.dp_id
        )
        if ATTR_BRIGHTNESS in kwargs and self._brightness_code:
            bcode = self._brightness_code
            max_scale = 1000 if bcode == "bright_value_v2" else 255
            scaled = max(10, round((int(kwargs[ATTR_BRIGHTNESS]) / 255.0) * max_scale))
            await self.coordinator.async_send_device_command(
                self._device_id, bcode, scaled, dp_id=22
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_device_command(
            self._device_id, self._spec.code, False, dp_id=self._spec.dp_id
        )
