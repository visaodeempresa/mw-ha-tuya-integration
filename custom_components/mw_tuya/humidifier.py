"""Plataforma `humidifier`: umidificadores (`jsq`) com modos do Thing Model."""

from __future__ import annotations

from typing import Any

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
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
    async_add_entities(
        MwTuyaHumidifier(coordinator, dev, spec)
        for dev in coordinator.active_devices
        for spec in infer_entity_specs(dev)
        if spec.platform == "humidifier"
    )


class MwTuyaHumidifier(MwTuyaEntity, HumidifierEntity):
    """Umidificador híbrido Local + Cloud."""

    _attr_device_class = HumidifierDeviceClass.HUMIDIFIER

    def __init__(self, coordinator, device, spec) -> None:
        super().__init__(coordinator, device, spec)
        ex = spec.extra
        self._c_switch: str = ex.get("switch") or spec.code
        self._c_mode: str | None = ex.get("mode")
        self._c_target: str | None = ex.get("target")
        self._c_current: str | None = ex.get("current")
        mode_spec = device.spec(self._c_mode) if self._c_mode else None
        self._attr_available_modes = (
            list(mode_spec.range) if mode_spec and mode_spec.range else None
        )
        if self._attr_available_modes:
            self._attr_supported_features = HumidifierEntityFeature.MODES
        tspec = device.spec(self._c_target) if self._c_target else None
        if tspec and tspec.max > tspec.min:
            self._attr_min_humidity = int(tspec.ha_min)
            self._attr_max_humidity = int(tspec.ha_max)

    def _scaled(self, code: str | None) -> float | None:
        val = self.status_of(code)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None
        dev = self.device_obj
        spec = dev.spec(code) if dev and code else None
        return spec.to_ha(val) if spec else val

    @property
    def is_on(self) -> bool | None:
        val = self.status_of(self._c_switch)
        return None if val is None else bool(val)

    @property
    def mode(self) -> str | None:
        val = self.status_of(self._c_mode)
        return str(val) if val is not None else None

    @property
    def target_humidity(self) -> float | None:
        return self._scaled(self._c_target)

    @property
    def current_humidity(self) -> float | None:
        return self._scaled(self._c_current)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.send({self._c_switch: True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.send({self._c_switch: False})

    async def async_set_mode(self, mode: str) -> None:
        if self._c_mode:
            await self.send({self._c_mode: mode})

    async def async_set_humidity(self, humidity: int) -> None:
        dev = self.device_obj
        if not self._c_target or not dev:
            return
        spec = dev.spec(self._c_target)
        await self.send({self._c_target: spec.from_ha(humidity) if spec else humidity})
