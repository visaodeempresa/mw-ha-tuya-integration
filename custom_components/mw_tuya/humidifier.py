"""Plataforma `humidifier` da MW Tuya Integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
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
    entities: list[MwTuyaHumidifier] = []
    for dev in coordinator.active_devices:
        for spec in infer_entity_specs(dev):
            if spec.platform == "humidifier":
                entities.append(MwTuyaHumidifier(coordinator, dev, spec))
    async_add_entities(entities)


class MwTuyaHumidifier(MwTuyaEntity, HumidifierEntity):
    """Umidificador inteligente híbrido Local + Cloud."""

    _attr_device_class = HumidifierDeviceClass.HUMIDIFIER
    _attr_min_humidity = 30
    _attr_max_humidity = 80

    @property
    def is_on(self) -> bool | None:
        val = self.dp_value
        if val is None:
            return None
        return bool(val)

    @property
    def current_humidity(self) -> int | None:
        dev = self.device_obj
        if not dev:
            return None
        for k in ("humidity_current", "va_humidity", "humidity_value"):
            val = dev.status.get(k)
            if isinstance(val, (int, float)):
                return int(val)
        return None

    @property
    def target_humidity(self) -> int | None:
        dev = self.device_obj
        if not dev:
            return None
        val = dev.status.get("humidity_set")
        if isinstance(val, (int, float)):
            return int(val)
        return 50

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_device_command(
            self._device_id, self._spec.code, True, dp_id=self._spec.dp_id
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_device_command(
            self._device_id, self._spec.code, False, dp_id=self._spec.dp_id
        )

    async def async_set_humidity(self, humidity: int) -> None:
        await self.coordinator.async_send_device_command(
            self._device_id, "humidity_set", int(humidity), dp_id=103
        )
