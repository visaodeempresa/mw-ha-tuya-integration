"""Plataforma `select`: opções vindas do Thing Model."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
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
        MwTuyaSelect(coordinator, dev, spec)
        for dev in coordinator.active_devices
        for spec in infer_entity_specs(dev)
        if spec.platform == "select"
    )


class MwTuyaSelect(MwTuyaEntity, SelectEntity):
    """Seleção de modo/estado (enum Tuya)."""

    def __init__(self, coordinator, device, spec) -> None:
        super().__init__(coordinator, device, spec)
        self._attr_options = list(spec.options)

    @property
    def current_option(self) -> str | None:
        val = self.dp_value
        return str(val) if val is not None and str(val) in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        await self.send({self._spec.code: option})
