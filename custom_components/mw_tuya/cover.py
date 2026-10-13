"""Plataforma `cover` da MW Tuya Integration (Cortinas e Motores de Janela)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
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
    entities: list[MwTuyaCover] = []
    for dev in coordinator.active_devices:
        for spec in infer_entity_specs(dev):
            if spec.platform == "cover":
                entities.append(MwTuyaCover(coordinator, dev, spec))
    async_add_entities(entities)


class MwTuyaCover(MwTuyaEntity, CoverEntity):
    """Cortina / Persiana / Janela híbrida Local + Cloud."""

    def __init__(self, coordinator: MwTuyaCoordinator, device, spec) -> None:
        super().__init__(coordinator, device, spec)
        self._attr_device_class = (
            CoverDeviceClass.WINDOW if spec.device_class == "window" else CoverDeviceClass.CURTAIN
        )
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        if "percent_control" in device.status or spec.code == "percent_control":
            features |= CoverEntityFeature.SET_POSITION
        self._attr_supported_features = features

    @property
    def current_cover_position(self) -> int | None:
        dev = self.device_obj
        if not dev:
            return None
        for key in ("percent_state", "percent_control"):
            val = dev.status.get(key)
            if isinstance(val, (int, float)):
                return max(0, min(100, int(val)))
        return None

    @property
    def is_closed(self) -> bool | None:
        pos = self.current_cover_position
        if pos is not None:
            return pos == 0
        dev = self.device_obj
        if dev and "control" in dev.status:
            return dev.status["control"] == "close"
        return None

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_device_command(
            self._device_id, "control", "open", dp_id=1
        )

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_device_command(
            self._device_id, "control", "close", dp_id=1
        )

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_device_command(
            self._device_id, "control", "stop", dp_id=1
        )

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        pos = int(kwargs.get(ATTR_POSITION, 50))
        await self.coordinator.async_send_device_command(
            self._device_id, "percent_control", pos, dp_id=2
        )
