"""Plataforma `event`: cliques de botões sem fio (categoria `wxkg`).

Cada clique chega pelo push em tempo real (Message Service). Sem push, a
leitura periódica só percebe quando o tipo de clique muda.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
        MwTuyaEvent(coordinator, dev, spec)
        for dev in coordinator.active_devices
        for spec in infer_entity_specs(dev)
        if spec.platform == "event"
    )


class MwTuyaEvent(MwTuyaEntity, EventEntity):
    """Botão sem fio (`single_click`…) ou alerta de câmera (`triggered`)."""

    def __init__(self, coordinator, device, spec) -> None:
        super().__init__(coordinator, device, spec)
        self._attr_event_types = list(spec.options)
        if not spec.extra.get("decode"):
            self._attr_device_class = EventDeviceClass.BUTTON
        self._last_seen: Any = device.status.get(spec.code)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_push_listener(self._device_id, self._on_push)
        )

    @callback
    def _on_push(self, status: dict[str, Any]) -> None:
        if self._spec.code in status:
            self._fire(status[self._spec.code])

    @callback
    def _fire(self, value: Any) -> None:
        self._last_seen = value
        if not isinstance(value, str) or not value:
            return
        if self._spec.extra.get("decode") == "base64":
            try:
                message = base64.b64decode(value).decode("utf-8", "replace")
            except (ValueError, binascii.Error):
                message = value
            self._trigger_event("triggered", {"message": message})
        else:
            if value not in self._attr_event_types:
                self._attr_event_types.append(value)
            self._trigger_event(value)
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        # Fallback sem push: só percebe troca de tipo de clique
        value = self.dp_value
        if not self.coordinator.push_connected and value != self._last_seen:
            self._fire(value)
            return
        super()._handle_coordinator_update()
