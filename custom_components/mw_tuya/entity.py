"""Entidade base unificada (um único Device para Local + Cloud)."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MwTuyaCoordinator
from .models import EntitySpec, MwTuyaDevice


class MwTuyaEntity(CoordinatorEntity[MwTuyaCoordinator]):
    """Entidade associada a um dispositivo híbrido MW Tuya."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MwTuyaCoordinator,
        device: MwTuyaDevice,
        spec: EntitySpec,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device.device_id
        self._spec = spec
        self._attr_unique_id = f"{device.device_id}_{spec.platform}_{spec.code}"
        self._attr_name = spec.name
        self._attr_entity_registry_enabled_default = spec.enabled_default
        if spec.icon:
            self._attr_icon = spec.icon
        if spec.entity_category == "config":
            self._attr_entity_category = EntityCategory.CONFIG
        elif spec.entity_category == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        label = device.product_name or device.category_label
        sub_model = device.model or device.category
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=device.name,
            manufacturer="Tuya",
            model=f"{label} ({sub_model})".strip(),
            serial_number=device.device_id,
            configuration_url="https://iot.tuya.com",
        )

    @property
    def device_obj(self) -> MwTuyaDevice | None:
        return self.coordinator.catalog_devices.get(self._device_id)

    @property
    def available(self) -> bool:
        dev = self.device_obj
        if dev is None:
            return False
        if dev.is_local_configured and self.coordinator.local_ok.get(self._device_id, False):
            return True
        return bool(dev.online)

    @property
    def dp_value(self) -> Any:
        dev = self.device_obj
        if dev is None:
            return None
        return dev.status.get(self._spec.code)

    def status_of(self, code: str | None) -> Any:
        dev = self.device_obj
        if dev is None or not code:
            return None
        return dev.status.get(code)

    async def send(self, commands: dict[str, Any]) -> None:
        """Envia vários DPs de uma vez (um único frame local quando possível)."""
        await self.coordinator.async_send_device_commands(self._device_id, commands)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        dev = self.device_obj
        if dev is None:
            return {}
        stats = self.coordinator.stats.get(self._device_id, {})
        return {
            "account": self.coordinator.account_name,
            "tuya_device_id": self._device_id,
            "tuya_category": dev.category,
            "dp_code": self._spec.code,
            "dp_id": self._spec.dp_id,
            "connection_mode": self.coordinator.routing_mode,
            "local_configured": dev.is_local_configured,
            "local_ip": dev.local_ip or None,
            "local_online": self.coordinator.local_ok.get(self._device_id, False)
            if dev.is_local_configured
            else False,
            "local_hits": stats.get("local_ok", 0),
            "cloud_hits": stats.get("cloud", 0) + stats.get("cloud_fallback", 0),
        }
