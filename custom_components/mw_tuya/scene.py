"""Plataforma `scene` da MW Tuya Integration — cria apenas as cenas selecionadas."""

from __future__ import annotations

from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MwTuyaCoordinator
from .models import MwTuyaScene


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MwTuyaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [MwTuyaSceneEntity(coordinator, scene) for scene in coordinator.active_scenes]
    async_add_entities(entities)


class MwTuyaSceneEntity(CoordinatorEntity[MwTuyaCoordinator], Scene):
    """Cena Tap-to-Run selecionada de uma conta Tuya."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MwTuyaCoordinator, scene: MwTuyaScene) -> None:
        super().__init__(coordinator)
        self._scene = scene
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_scene_{scene.scene_id}"
        self._attr_name = scene.name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"account_{coordinator.config_entry.entry_id}")},
            name=f"MW Tuya · {coordinator.account_name}",
            manufacturer="Tuya",
            model="Tuya Cloud Account Hub",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "account": self.coordinator.account_name,
            "scene_id": self._scene.scene_id,
            "home_id": self._scene.home_id,
            "home_name": self._scene.home_name,
        }

    async def async_activate(self, **kwargs: Any) -> None:
        await self.coordinator.async_trigger_scene(self._scene.scene_id)
