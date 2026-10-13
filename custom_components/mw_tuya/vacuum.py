"""Plataforma `vacuum`: robôs aspiradores Tuya (categoria `sd`)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MwTuyaCoordinator
from .entity import MwTuyaEntity
from .models import infer_entity_specs

ACTIVITY = {
    "standby": VacuumActivity.IDLE,
    "sleep": VacuumActivity.IDLE,
    "paused": VacuumActivity.PAUSED,
    "pause": VacuumActivity.PAUSED,
    "goto_charge": VacuumActivity.RETURNING,
    "charging": VacuumActivity.DOCKED,
    "charge_done": VacuumActivity.DOCKED,
    "chargecompleted": VacuumActivity.DOCKED,
    "docking": VacuumActivity.RETURNING,
    "err": VacuumActivity.ERROR,
    "error": VacuumActivity.ERROR,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MwTuyaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        MwTuyaVacuum(coordinator, dev, spec)
        for dev in coordinator.active_devices
        for spec in infer_entity_specs(dev)
        if spec.platform == "vacuum"
    )


class MwTuyaVacuum(MwTuyaEntity, StateVacuumEntity):
    """Aspirador robô."""

    def __init__(self, coordinator, device, spec) -> None:
        super().__init__(coordinator, device, spec)
        ex = spec.extra
        self._c_power: str = ex.get("power") or spec.code
        self._c_mode: str | None = ex.get("mode")
        self._c_status: str | None = ex.get("status")
        self._c_seek: str | None = ex.get("seek")
        self._c_charge: str | None = ex.get("charge")
        self._c_pause: str | None = ex.get("pause")
        self._c_suction: str | None = ex.get("suction")
        feats = (
            VacuumEntityFeature.START
            | VacuumEntityFeature.STOP
            | VacuumEntityFeature.STATE
            | VacuumEntityFeature.TURN_ON
            | VacuumEntityFeature.TURN_OFF
        )
        if self._c_pause or self._c_power:
            feats |= VacuumEntityFeature.PAUSE
        if self._c_charge or self._modes_has("chargego"):
            feats |= VacuumEntityFeature.RETURN_HOME
        if self._c_seek:
            feats |= VacuumEntityFeature.LOCATE
        if self._c_suction and self._enum(self._c_suction):
            feats |= VacuumEntityFeature.FAN_SPEED
            self._attr_fan_speed_list = self._enum(self._c_suction)
        self._attr_supported_features = feats

    def _enum(self, code: str | None) -> list[str]:
        dev = self.device_obj
        spec = dev.spec(code) if dev and code else None
        return list(spec.range) if spec and spec.range else []

    def _modes_has(self, value: str) -> bool:
        return value in self._enum(self._c_mode)

    @property
    def activity(self) -> VacuumActivity | None:
        raw = self.status_of(self._c_status)
        if isinstance(raw, str):
            low = raw.lower()
            if low in ACTIVITY:
                return ACTIVITY[low]
            if "clean" in low or low in ("smart", "spiral", "wall_follow", "remote"):
                return VacuumActivity.CLEANING
        if self.status_of(self._c_power):
            return VacuumActivity.CLEANING
        return VacuumActivity.IDLE

    @property
    def fan_speed(self) -> str | None:
        val = self.status_of(self._c_suction)
        return val if isinstance(val, str) else None

    async def async_start(self, **kwargs: Any) -> None:
        cmds: dict[str, Any] = {self._c_power: True}
        if self._c_mode and self._modes_has("smart"):
            cmds[self._c_mode] = "smart"
        await self.send(cmds)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.async_start()

    async def async_stop(self, **kwargs: Any) -> None:
        await self.send({self._c_power: False})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_stop()

    async def async_pause(self, **kwargs: Any) -> None:
        if self._c_pause:
            await self.send({self._c_pause: True})
        else:
            await self.send({self._c_power: False})

    async def async_return_to_base(self, **kwargs: Any) -> None:
        if self._c_charge:
            await self.send({self._c_charge: True})
        elif self._c_mode:
            await self.send({self._c_mode: "chargego"})

    async def async_locate(self, **kwargs: Any) -> None:
        if self._c_seek:
            await self.send({self._c_seek: True})

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        if self._c_suction:
            await self.send({self._c_suction: fan_speed})
