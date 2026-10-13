"""Plataforma `climate` da MW Tuya Integration."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
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
    entities: list[MwTuyaClimate] = []
    for dev in coordinator.active_devices:
        for spec in infer_entity_specs(dev):
            if spec.platform == "climate":
                entities.append(MwTuyaClimate(coordinator, dev, spec))
    async_add_entities(entities)


class MwTuyaClimate(MwTuyaEntity, ClimateEntity):
    """Ar-Condicionado / Climatizador híbrido Local + Cloud."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes: ClassVar[list[HVACMode]] = [
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.FAN_ONLY,
        HVACMode.AUTO,
    ]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = 16.0
    _attr_max_temp = 30.0
    _attr_target_temperature_step = 1.0

    @property
    def hvac_mode(self) -> HVACMode:
        dev = self.device_obj
        if not dev or not dev.status.get("switch", False):
            return HVACMode.OFF
        mode = str(dev.status.get("mode") or "cold").lower()
        if mode in ("cold", "cool"):
            return HVACMode.COOL
        if mode in ("hot", "heat"):
            return HVACMode.HEAT
        if mode in ("wind", "fan"):
            return HVACMode.FAN_ONLY
        return HVACMode.AUTO

    @property
    def current_temperature(self) -> float | None:
        dev = self.device_obj
        if not dev:
            return None
        val = dev.status.get("temp_current")
        if isinstance(val, (int, float)):
            return float(val)
        return None

    @property
    def target_temperature(self) -> float | None:
        dev = self.device_obj
        if not dev:
            return None
        val = dev.status.get("temp_set")
        if isinstance(val, (int, float)):
            return float(val)
        return 22.0

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_send_device_command(
                self._device_id, "switch", False, dp_id=1
            )
            return
        await self.coordinator.async_send_device_command(self._device_id, "switch", True, dp_id=1)
        mode_map = {
            HVACMode.COOL: "cold",
            HVACMode.HEAT: "hot",
            HVACMode.FAN_ONLY: "wind",
            HVACMode.AUTO: "auto",
        }
        if hvac_mode in mode_map:
            await self.coordinator.async_send_device_command(
                self._device_id, "mode", mode_map[hvac_mode], dp_id=4
            )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await self.coordinator.async_send_device_command(
                self._device_id, "temp_set", round(float(temp)), dp_id=2
            )
