"""Plataforma `button` da MW Tuya Integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    entities: list[MwTuyaButton] = []
    for dev in coordinator.active_devices:
        for spec in infer_entity_specs(dev):
            if spec.platform == "button":
                entities.append(MwTuyaButton(coordinator, dev, spec))
    async_add_entities(entities)


class MwTuyaButton(MwTuyaEntity, ButtonEntity):
    """Botão de ação híbrido Local + Cloud (ex.: `filter_reset`, `reset_add_ele`)."""

    def __init__(
        self,
        coordinator: MwTuyaCoordinator,
        device: MwTuyaDevice,
        spec: EntitySpec,
    ) -> None:
        super().__init__(coordinator, device, spec)
        if spec.entity_category == "config":
            self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self.coordinator.async_send_device_command(
            self._device_id,
            self._spec.code,
            True,
            dp_id=self._spec.dp_id,
        )
