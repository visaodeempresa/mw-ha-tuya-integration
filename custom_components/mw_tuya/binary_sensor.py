"""Plataforma `binary_sensor`: contato, movimento, presença, vazamento..."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
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
        MwTuyaBinarySensor(coordinator, dev, spec)
        for dev in coordinator.active_devices
        for spec in infer_entity_specs(dev)
        if spec.platform == "binary_sensor"
    )


class MwTuyaBinarySensor(MwTuyaEntity, BinarySensorEntity):
    """Sensor binário derivado de DP bool ou enum."""

    def __init__(self, coordinator, device, spec) -> None:
        super().__init__(coordinator, device, spec)
        if spec.device_class:
            try:
                self._attr_device_class = BinarySensorDeviceClass(spec.device_class)
            except ValueError:
                self._attr_device_class = None
        self._on_values = {o.lower() for o in spec.options} or {"true"}

    @property
    def is_on(self) -> bool | None:
        val = self.dp_value
        if val is None:
            return None
        return str(val).lower() in self._on_values
