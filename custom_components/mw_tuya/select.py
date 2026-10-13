"""Plataforma `select` da MW Tuya Integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
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
    entities: list[MwTuyaSelect] = []
    for dev in coordinator.active_devices:
        for spec in infer_entity_specs(dev):
            if spec.platform == "select":
                entities.append(MwTuyaSelect(coordinator, dev, spec))
    async_add_entities(entities)


class MwTuyaSelect(MwTuyaEntity, SelectEntity):
    """Seletor de opção híbrido Local + Cloud (ex.: `relay_status`, `light_mode`)."""

    def __init__(
        self,
        coordinator: MwTuyaCoordinator,
        device: MwTuyaDevice,
        spec: EntitySpec,
    ) -> None:
        super().__init__(coordinator, device, spec)
        self._attr_options = list(spec.options)
        if spec.entity_category == "config":
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def current_option(self) -> str | None:
        dev = self.device_obj
        if not dev:
            return None
        val = dev.status.get(self._spec.code)
        if val is None:
            return None
        s_val = str(val)
        if s_val not in self._attr_options:
            self._attr_options = [*self._attr_options, s_val]
        return s_val

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_send_device_command(
            self._device_id,
            self._spec.code,
            option,
            dp_id=self._spec.dp_id,
        )
