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
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_UID, DOMAIN
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
    _attr_state_class = SensorStateClass.MEASUREMENT

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
    def available(self) -> bool:
        return True

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
        uid = c.client.uid if c.client is not None else str(c.config_entry.data.get(CONF_UID) or "")
        return {
            "account_name": c.account_name,
            "uid": uid,
            "routing_mode": c.routing_mode,
            "catalog_total_devices": len(c.catalog_devices),
            "selected_devices_count": len(c.active_devices),
            "catalog_total_scenes": len(c.catalog_scenes),
            "selected_scenes_count": len(c.active_scenes),
            "devices_with_local_key": local_keys_count,
            "lan_discovered_count": len(c.lan_map),
            "active_local_sockets": len(c.local_clients),
            "push_connected": c.push_connected,
        }


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
