"""Plataforma `sensor` da MW Tuya Integration (Medidores de Energia, Ambiente e Hub da Conta)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MwTuyaCoordinator
from .entity import MwTuyaEntity
from .models import infer_entity_specs

_DEVICE_CLASS_MAP: dict[str, SensorDeviceClass] = {
    "current": SensorDeviceClass.CURRENT,
    "power": SensorDeviceClass.POWER,
    "voltage": SensorDeviceClass.VOLTAGE,
    "energy": SensorDeviceClass.ENERGY,
    "temperature": SensorDeviceClass.TEMPERATURE,
    "humidity": SensorDeviceClass.HUMIDITY,
    "illuminance": SensorDeviceClass.ILLUMINANCE,
    "pm25": SensorDeviceClass.PM25,
    "carbon_dioxide": SensorDeviceClass.CARBON_DIOXIDE,
    "volatile_organic_compounds": SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
    "battery": SensorDeviceClass.BATTERY,
    "distance": SensorDeviceClass.DISTANCE,
}

_STATE_CLASS_MAP: dict[str, SensorStateClass] = {
    "measurement": SensorStateClass.MEASUREMENT,
    "total_increasing": SensorStateClass.TOTAL_INCREASING,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MwTuyaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [MwTuyaAccountStatusSensor(coordinator)]
    for dev in coordinator.active_devices:
        for spec in infer_entity_specs(dev):
            if spec.platform == "sensor":
                entities.append(MwTuyaSensor(coordinator, dev, spec))
    async_add_entities(entities)


class MwTuyaAccountStatusSensor(CoordinatorEntity[MwTuyaCoordinator], SensorEntity):
    """Sensor de diagnóstico da conta Tuya (mostra inventário descoberto vs selecionado)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-check-variant"

    def __init__(self, coordinator: MwTuyaCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_account_status"
        self._attr_name = "Catálogo da Conta"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"account_{coordinator.config_entry.entry_id}")},
            name=f"MW Tuya · {coordinator.account_name}",
            manufacturer="Tuya",
            model="Tuya Cloud Account Hub",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> int:
        return len(self.coordinator.active_devices)

    @property
    def native_unit_of_measurement(self) -> str:
        return "dispositivos ativos"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.coordinator
        local_keys_count = sum(1 for d in c.catalog_devices.values() if d.has_valid_local_key)
        return {
            "account_name": c.account_name,
            "uid": c.client.uid,
            "routing_mode": c.routing_mode,
            "catalog_total_devices": len(c.catalog_devices),
            "selected_devices_count": len(c.active_devices),
            "catalog_total_scenes": len(c.catalog_scenes),
            "selected_scenes_count": len(c.active_scenes),
            "devices_with_local_key": local_keys_count,
            "lan_discovered_count": len(c.lan_map),
            "active_local_sockets": len(c.local_clients),
        }


class MwTuyaSensor(MwTuyaEntity, SensorEntity):
    """Sensor numérico de um dispositivo híbrido MW Tuya."""

    def __init__(self, coordinator: MwTuyaCoordinator, device, spec) -> None:
        super().__init__(coordinator, device, spec)
        if spec.device_class and spec.device_class in _DEVICE_CLASS_MAP:
            self._attr_device_class = _DEVICE_CLASS_MAP[spec.device_class]
        if spec.state_class and spec.state_class in _STATE_CLASS_MAP:
            self._attr_state_class = _STATE_CLASS_MAP[spec.state_class]
        self._attr_native_unit_of_measurement = spec.unit

    @property
    def native_value(self) -> float | int | None:
        val = self.dp_value
        if not isinstance(val, (int, float)):
            return None
        if self._spec.scale != 1.0:
            return round(float(val) * self._spec.scale, 3)
        return val
