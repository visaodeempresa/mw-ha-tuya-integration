"""Plataforma `fan`: purificadores e ventiladores (velocidade, preset, direção, oscilação)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

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
    async_add_entities(
        MwTuyaFan(coordinator, dev, spec)
        for dev in coordinator.active_devices
        for spec in infer_entity_specs(dev)
        if spec.platform == "fan"
    )


class MwTuyaFan(MwTuyaEntity, FanEntity):
    """Purificador de ar / ventilador híbrido Local + Cloud."""

    def __init__(self, coordinator, device, spec) -> None:
        super().__init__(coordinator, device, spec)
        ex = spec.extra
        self._c_switch: str = ex.get("switch") or spec.code
        self._c_speed: str | None = ex.get("speed")
        self._c_preset: str | None = ex.get("preset")
        self._c_dir: str | None = ex.get("direction")
        self._c_osc: str | None = ex.get("oscillate")
        self._speed_list: list[str] = []
        self._speed_lo = self._speed_hi = 0
        sp = device.spec(self._c_speed) if self._c_speed else None
        if sp and sp.type == "enum":
            self._speed_list = list(sp.range)
        elif sp and sp.type == "value":
            self._speed_lo, self._speed_hi = int(max(sp.min, 1)), int(sp.max)
        presets = (
            device.spec(self._c_preset).range
            if self._c_preset and device.spec(self._c_preset)
            else []
        )
        self._attr_preset_modes = list(presets) or None

        feats = FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
        if self._speed_list or self._speed_hi:
            feats |= FanEntityFeature.SET_SPEED
            self._attr_speed_count = len(self._speed_list) or (self._speed_hi - self._speed_lo + 1)
        if self._attr_preset_modes:
            feats |= FanEntityFeature.PRESET_MODE
        if self._c_dir:
            feats |= FanEntityFeature.DIRECTION
        if self._c_osc:
            feats |= FanEntityFeature.OSCILLATE
        self._attr_supported_features = feats

    @property
    def is_on(self) -> bool | None:
        val = self.status_of(self._c_switch)
        return None if val is None else bool(val)

    @property
    def percentage(self) -> int | None:
        val = self.status_of(self._c_speed)
        if val is None:
            return None
        if self._speed_list:
            return (
                ordered_list_item_to_percentage(self._speed_list, str(val))
                if str(val) in self._speed_list
                else None
            )
        if self._speed_hi and isinstance(val, (int, float)):
            span = max(1, self._speed_hi - self._speed_lo)
            return round((val - self._speed_lo) / span * 100)
        return None

    @property
    def preset_mode(self) -> str | None:
        val = self.status_of(self._c_preset)
        return str(val) if val is not None else None

    @property
    def current_direction(self) -> str | None:
        val = self.status_of(self._c_dir)
        return str(val) if val is not None else None

    @property
    def oscillating(self) -> bool | None:
        val = self.status_of(self._c_osc)
        return None if val is None else bool(val)

    def _speed_cmd(self, percentage: int) -> Any:
        if self._speed_list:
            return percentage_to_ordered_list_item(self._speed_list, percentage)
        return round(self._speed_lo + percentage / 100 * (self._speed_hi - self._speed_lo))

    async def async_turn_on(
        self, percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any
    ) -> None:
        cmds: dict[str, Any] = {self._c_switch: True}
        if percentage is not None and self._c_speed:
            cmds[self._c_speed] = self._speed_cmd(percentage)
        if preset_mode is not None and self._c_preset:
            cmds[self._c_preset] = preset_mode
        await self.send(cmds)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.send({self._c_switch: False})

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self.async_turn_off()
            return
        await self.send({self._c_switch: True, self._c_speed: self._speed_cmd(percentage)})  # type: ignore[dict-item]

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self.send({self._c_preset: preset_mode})  # type: ignore[dict-item]

    async def async_set_direction(self, direction: str) -> None:
        await self.send({self._c_dir: direction})  # type: ignore[dict-item]

    async def async_oscillate(self, oscillating: bool) -> None:
        await self.send({self._c_osc: oscillating})  # type: ignore[dict-item]
