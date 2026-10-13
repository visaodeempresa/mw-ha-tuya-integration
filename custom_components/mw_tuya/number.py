"""Plataforma `number`: faixa, passo, escala e unidade vindos do Thing Model."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
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
        MwTuyaNumber(coordinator, dev, spec)
        for dev in coordinator.active_devices
        for spec in infer_entity_specs(dev)
        if spec.platform == "number"
    )


class MwTuyaNumber(MwTuyaEntity, NumberEntity):
    """Ajuste numérico (timer, sensibilidade, distância...)."""

    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, device, spec) -> None:
        super().__init__(coordinator, device, spec)
        self._attr_native_min_value = spec.min_value
        self._attr_native_max_value = spec.max_value
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = spec.unit

    @property
    def native_value(self) -> float | None:
        val = self.dp_value
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None
        return float(self._spec.dp.to_ha(val)) if self._spec.dp else float(val)

    async def async_set_native_value(self, value: float) -> None:
        raw = self._spec.dp.from_ha(value) if self._spec.dp else round(value)
        await self.send({self._spec.code: raw})
