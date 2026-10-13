"""Plataforma `cover`: cortinas (`cl`) e motores de janela (`mc`, `wd_*`)."""

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
    async_add_entities(
        MwTuyaCover(coordinator, dev, spec)
        for dev in coordinator.active_devices
        for spec in infer_entity_specs(dev)
        if spec.platform == "cover"
    )


def _pick(options: list[str], *wanted: str) -> str | None:
    for w in wanted:
        if w in options:
            return w
    return None


class MwTuyaCover(MwTuyaEntity, CoverEntity):
    """Cortina / janela híbrida Local + Cloud."""

    def __init__(self, coordinator, device, spec) -> None:
        super().__init__(coordinator, device, spec)
        ex = spec.extra
        self._c_control: str | None = ex.get("control")
        self._c_pos: str | None = ex.get("position")
        self._c_state: str | None = ex.get("state")
        self._c_wstate: str | None = ex.get("window_state")
        self._attr_device_class = (
            CoverDeviceClass.WINDOW if spec.device_class == "window" else CoverDeviceClass.CURTAIN
        )
        ctrl_spec = device.spec(self._c_control) if self._c_control else None
        opts = list(ctrl_spec.range) if ctrl_spec and ctrl_spec.range else ["open", "close", "stop"]
        self._v_open = _pick(opts, "open", "FZ")
        self._v_close = _pick(opts, "close", "ZZ")
        self._v_stop = _pick(opts, "stop", "pause", "STOP")
        feats = CoverEntityFeature(0)
        if self._c_control and self._v_open:
            feats |= CoverEntityFeature.OPEN
        if self._c_control and self._v_close:
            feats |= CoverEntityFeature.CLOSE
        if self._c_control and self._v_stop:
            feats |= CoverEntityFeature.STOP
        if self._c_pos:
            feats |= CoverEntityFeature.SET_POSITION
            if not self._c_control:
                feats |= CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        self._attr_supported_features = feats

    @property
    def current_cover_position(self) -> int | None:
        for code in (self._c_state, self._c_pos):
            val = self.status_of(code)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                return max(0, min(100, int(val)))
        return None

    @property
    def is_closed(self) -> bool | None:
        wstate = self.status_of(self._c_wstate)
        if wstate in ("opened", "closed"):
            return wstate == "closed"
        pos = self.current_cover_position
        if pos is not None:
            return pos == 0
        val = self.status_of(self._c_control)
        return None if val is None else val == self._v_close

    @property
    def is_opening(self) -> bool | None:
        return (
            self.status_of(self._c_wstate) == "pending"
            and self.status_of(self._c_control) == self._v_open
        )

    @property
    def is_closing(self) -> bool | None:
        return (
            self.status_of(self._c_wstate) == "pending"
            and self.status_of(self._c_control) == self._v_close
        )

    async def async_open_cover(self, **kwargs: Any) -> None:
        if self._c_control and self._v_open:
            await self.send({self._c_control: self._v_open})
        elif self._c_pos:
            await self.send({self._c_pos: 100})

    async def async_close_cover(self, **kwargs: Any) -> None:
        if self._c_control and self._v_close:
            await self.send({self._c_control: self._v_close})
        elif self._c_pos:
            await self.send({self._c_pos: 0})

    async def async_stop_cover(self, **kwargs: Any) -> None:
        if self._c_control and self._v_stop:
            await self.send({self._c_control: self._v_stop})

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        if self._c_pos:
            await self.send({self._c_pos: int(kwargs.get(ATTR_POSITION, 50))})
