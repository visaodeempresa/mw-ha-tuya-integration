"""Plataforma `binary_sensor` da MW Tuya Integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MwTuyaCoordinator
from .entity import MwTuyaEntity
from .models import infer_entity_specs

_BIN_CLASS_MAP: dict[str, BinarySensorDeviceClass] = {
    "door": BinarySensorDeviceClass.DOOR,
    "motion": BinarySensorDeviceClass.MOTION,
    "occupancy": BinarySensorDeviceClass.OCCUPANCY,
    "safety": BinarySensorDeviceClass.SAFETY,
    "vibration": BinarySensorDeviceClass.VIBRATION,
    "moisture": BinarySensorDeviceClass.MOISTURE,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MwTuyaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[MwTuyaBinarySensor] = []
    for dev in coordinator.active_devices:
        for spec in infer_entity_specs(dev):
            if spec.platform == "binary_sensor":
                entities.append(MwTuyaBinarySensor(coordinator, dev, spec))
    async_add_entities(entities)


class MwTuyaBinarySensor(MwTuyaEntity, BinarySensorEntity):
    """Sensor binário de presença, movimento, contato ou alarme."""

    def __init__(self, coordinator: MwTuyaCoordinator, device, spec) -> None:
        super().__init__(coordinator, device, spec)
        if spec.device_class and spec.device_class in _BIN_CLASS_MAP:
            self._attr_device_class = _BIN_CLASS_MAP[spec.device_class]

    @property
    def is_on(self) -> bool | None:
        val = self.dp_value
        if val is None:
            return None
        if isinstance(val, bool):
            return val
        if self._spec.options:
            return str(val).lower() in {o.lower() for o in self._spec.options}
        return bool(val)
