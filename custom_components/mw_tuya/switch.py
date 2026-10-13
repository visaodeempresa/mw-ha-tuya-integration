"""Plataforma `switch`: tomadas, canais e chaves de configuração."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
        MwTuyaSwitch(coordinator, dev, spec)
        for dev in coordinator.active_devices
        for spec in infer_entity_specs(dev)
        if spec.platform == "switch"
    )


class MwTuyaSwitch(MwTuyaEntity, SwitchEntity):
    """Interruptor / tomada híbrida Local + Cloud."""

    @property
    def is_on(self) -> bool | None:
        val = self.dp_value
        return None if val is None else bool(val)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.send({self._spec.code: True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.send({self._spec.code: False})
