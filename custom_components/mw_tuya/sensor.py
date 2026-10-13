"""Plataforma `sensor`: escala/unidade do Thing Model; enums como sensor ENUM."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MwTuyaCoordinator
from .entity import MwTuyaEntity
from .models import infer_entity_specs


def _device_class(name: str | None) -> SensorDeviceClass | None:
    if not name:
        return None
    try:
        return SensorDeviceClass(name)
    except ValueError:
        return None


def _state_class(name: str | None) -> SensorStateClass | None:
    if not name:
        return None
    try:
        return SensorStateClass(name)
    except ValueError:
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MwTuyaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        MwTuyaSensor(coordinator, dev, spec)
        for dev in coordinator.active_devices
        for spec in infer_entity_specs(dev)
        if spec.platform == "sensor"
    )


class MwTuyaSensor(MwTuyaEntity, SensorEntity):
    """Sensor de energia, ambiente, bateria ou estado."""

    def __init__(self, coordinator: MwTuyaCoordinator, device, spec) -> None:
        super().__init__(coordinator, device, spec)
        dclass = _device_class(spec.device_class)
        self._attr_device_class = dclass
        if dclass == SensorDeviceClass.ENUM:
            self._attr_options = list(spec.options) or None
        else:
            self._attr_native_unit_of_measurement = spec.unit
            self._attr_state_class = _state_class(spec.state_class)

    @property
    def native_value(self) -> Any:
        val = self.dp_value
        if val is None:
            return None
        if self._attr_device_class == SensorDeviceClass.ENUM:
            sval = str(val)
            return sval if not self._attr_options or sval in self._attr_options else None
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return val
        if self._spec.dp:
            return self._spec.dp.to_ha(val)
        return val
