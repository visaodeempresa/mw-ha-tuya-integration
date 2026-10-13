"""Plataforma `number` da MW Tuya Integration."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MwTuyaCoordinator
from .entity import MwTuyaEntity
from .models import EntitySpec, MwTuyaDevice, infer_entity_specs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MwTuyaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[MwTuyaNumber] = []
    for dev in coordinator.active_devices:
        for spec in infer_entity_specs(dev):
            if spec.platform == "number":
                entities.append(MwTuyaNumber(coordinator, dev, spec))
    async_add_entities(entities)


class MwTuyaNumber(MwTuyaEntity, NumberEntity):
    """Entidade numérica híbrida Local + Cloud (ex.: `countdown_1`, sensibilidade mmWave)."""

    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: MwTuyaCoordinator,
        device: MwTuyaDevice,
        spec: EntitySpec,
    ) -> None:
        super().__init__(coordinator, device, spec)
        self._attr_native_min_value = spec.min_value
        self._attr_native_max_value = spec.max_value
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = spec.unit
        if spec.entity_category == "config":
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self) -> float | None:
        dev = self.device_obj
        if not dev:
            return None
        val = dev.status.get(self._spec.code)
        if isinstance(val, (int, float)):
            return float(val)
        return None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_send_device_command(
            self._device_id,
            self._spec.code,
            round(value),
            dp_id=self._spec.dp_id,
        )
