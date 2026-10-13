"""Plataforma `camera`: câmeras IPC Tuya (categoria `sp`).

O vídeo vem do endpoint OpenAPI `stream/actions/allocate` (RTSP). Ele exige a
assinatura do serviço **IoT Video Live Stream** no projeto Tuya IoT; sem ela a
câmera continua disponível para privacidade, gravação e detecção de movimento,
apenas sem imagem.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.camera import Camera as CameraEntity
from homeassistant.components.camera import CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import TuyaApiError
from .const import DOMAIN
from .coordinator import MwTuyaCoordinator
from .entity import MwTuyaEntity
from .models import infer_entity_specs

_LOGGER = logging.getLogger(__name__)
# URLs RTSP da Tuya expiram; renova antes disso
STREAM_TTL = 240.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MwTuyaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        MwTuyaCamera(coordinator, dev, spec)
        for dev in coordinator.active_devices
        for spec in infer_entity_specs(dev)
        if spec.platform == "camera"
    )


class MwTuyaCamera(MwTuyaEntity, CameraEntity):
    """Câmera IPC Tuya."""

    _attr_brand = "Tuya"

    def __init__(self, coordinator, device, spec) -> None:
        MwTuyaEntity.__init__(self, coordinator, device, spec)
        CameraEntity.__init__(self)
        ex = spec.extra
        self._c_private: str | None = ex.get("private")
        self._c_record: str | None = ex.get("record")
        self._c_motion: str | None = ex.get("motion")
        self._attr_model = device.product_name or None
        self._attr_supported_features = CameraEntityFeature.STREAM
        if self._c_private:
            self._attr_supported_features |= CameraEntityFeature.ON_OFF
        self._stream_url: str | None = None
        self._stream_at = 0.0
        self._stream_denied = False

    # ------------------------------------------------------------------ estado
    @property
    def is_on(self) -> bool:
        if not self._c_private:
            return True
        return not bool(self.status_of(self._c_private))

    @property
    def is_recording(self) -> bool:
        return bool(self.status_of(self._c_record)) if self._c_record else False

    @property
    def motion_detection_enabled(self) -> bool:
        return bool(self.status_of(self._c_motion)) if self._c_motion else False

    # ------------------------------------------------------------------ vídeo
    async def stream_source(self) -> str | None:
        if self._stream_denied or not self.is_on:
            return None
        if self._stream_url and time.monotonic() - self._stream_at < STREAM_TTL:
            return self._stream_url
        try:
            res = await self.coordinator.client.async_post(
                f"/v1.0/devices/{self._device_id}/stream/actions/allocate", {"type": "rtsp"}
            )
        except TuyaApiError as err:
            if err.code in (28841101, 1106):
                self._stream_denied = True
                _LOGGER.warning(
                    "Câmera %s sem vídeo: assine o serviço 'IoT Video Live Stream' no "
                    "projeto Tuya IoT e recarregue a integração",
                    self.entity_id,
                )
            else:
                _LOGGER.debug("Falha ao alocar stream de %s: %s", self.entity_id, err)
            return None
        url = (res or {}).get("url") if isinstance(res, dict) else None
        self._stream_url, self._stream_at = url, time.monotonic()
        return url

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        source = await self.stream_source()
        if not source:
            return None
        from homeassistant.components import ffmpeg

        return await ffmpeg.async_get_image(self.hass, source, width=width, height=height)

    # ------------------------------------------------------------------ comandos
    async def async_turn_on(self) -> None:
        if self._c_private:
            await self.send({self._c_private: False})

    async def async_turn_off(self) -> None:
        if self._c_private:
            await self.send({self._c_private: True})

    async def async_enable_motion_detection(self) -> None:
        if self._c_motion:
            await self.send({self._c_motion: True})

    async def async_disable_motion_detection(self) -> None:
        if self._c_motion:
            await self.send({self._c_motion: False})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        attrs["stream_api"] = "negado" if self._stream_denied else "ok"
        return attrs
