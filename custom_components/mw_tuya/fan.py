"""Plataforma `fan` da MW Tuya Integration (Purificadores de Ar e Ventiladores)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
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
    entities: list[MwTuyaFan] = []
    for dev in coordinator.active_devices:
        for spec in infer_entity_specs(dev):
            if spec.platform == "fan":
                entities.append(MwTuyaFan(coordinator, dev, spec))
    async_add_entities(entities)


class MwTuyaFan(MwTuyaEntity, FanEntity):
    """Purificador de Ar / Ventilador híbrido Local + Cloud."""

    _attr_supported_features = FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF

    @property
    def is_on(self) -> bool | None:
        val = self.dp_value
        if val is None:
            return None
        return bool(val)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        await self.coordinator.async_send_device_command(
            self._device_id, self._spec.code, True, dp_id=self._spec.dp_id
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_device_command(
            self._device_id, self._spec.code, False, dp_id=self._spec.dp_id
        )
