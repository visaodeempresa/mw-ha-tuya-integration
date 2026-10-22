"""Plataforma `camera`: câmeras IPC Tuya (categoria `sp`).

Prioriza o servidor ONVIF/RTSP Local LAN (`rtsp://admin:admin@<ip>:<port>/<path>`)
com auto-ativação do DP `onvif_switch` via protocolo local Tuya 3.4 (TCP 6668),
mantendo buffer de snapshots ao vivo em RAM (`tmpfs` em `/dev/shm/leticia_snapshots`
vinculado a `/tmp/leticia_snapshots`) e zero dependência de nuvem ou fotos antigas.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path
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
from .local import TuyaLocalClient
from .models import infer_entity_specs
from .smartlife import SmartLifeError

_LOGGER = logging.getLogger(__name__)

# URLs RTSP da nuvem Tuya expiram; renova antes disso (local RTSP não expira)
STREAM_TTL = 240.0
STREAM_RETRY_COOLDOWN = 60.0
# Cache curtíssimo (1.5s) apenas para deduplicar chamadas simultâneas no mesmo segundo
IMAGE_CACHE_TTL = 1.5

SHM_SNAPSHOT_DIR = Path("/dev/shm/leticia_snapshots")
TMP_SNAPSHOT_LINK = Path("/tmp/leticia_snapshots")
MEDIA_SNAPSHOT_DIR = Path("/media/snapshots")

LOCAL_RTSP_MAP: dict[str, dict[str, Any]] = {
    "ebdd8148c3a99185c6dyae": {
        "camera_slug": "camera_do_escritorio",
        "room_slug": "escritorio",
        "ip": "192.168.1.154",
        "port": 5543,
        "path": "/21232f297a57a5a743894a0e4a801fc3/live/channel0",
        "onvif_dp": 237,
    },
    "eb93be8f07133be5cdymbk": {
        "camera_slug": "camera_da_cozinha",
        "room_slug": "cozinha",
        "ip": "192.168.1.29",
        "port": 5543,
        "path": "/21232f297a57a5a743894a0e4a801fc3/live/channel0",
        "onvif_dp": 237,
    },
    "eb9dd8497774fa050bwyjl": {
        "camera_slug": "camera_da_sala",
        "room_slug": "sala_tv",
        "ip": "192.168.1.11",
        "port": 554,
        "path": "/V_ENC_000",
        "onvif_dp": 234,
    },
    "eb8394a828d20e7d0eygej": {
        "camera_slug": "camera_da_sala_de_yoga",
        "room_slug": "sala_jantar",
        "ip": "192.168.1.137",
        "port": 5543,
        "path": "/21232f297a57a5a743894a0e4a801fc3/live/channel0",
        "onvif_dp": 237,
    },
    "eb244ebed2360f04914fsp": {
        "camera_slug": "camera_do_quarto",
        "room_slug": "quarto",
        "ip": "192.168.1.180",
        "port": 5543,
        "path": "/21232f297a57a5a743894a0e4a801fc3/live/channel0",
        "onvif_dp": 237,
    },
    "ebd974663b587a2777a8rk": {
        "camera_slug": "camera_da_suite",
        "room_slug": "suite",
        "ip": "192.168.1.196",
        "port": 5543,
        "path": "/21232f297a57a5a743894a0e4a801fc3/live/channel0",
        "onvif_dp": 237,
    },
}

DEVICE_ROOM_MAP: dict[str, tuple[str, str]] = {
    did: (cfg["camera_slug"], cfg["room_slug"]) for did, cfg in LOCAL_RTSP_MAP.items()
}


def _ensure_tmpfs_dirs() -> Path:
    """Garante diretório em RAM (tmpfs /dev/shm) com link em /tmp/leticia_snapshots."""
    try:
        SHM_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        for _, room in DEVICE_ROOM_MAP.values():
            (SHM_SNAPSHOT_DIR / room).mkdir(parents=True, exist_ok=True)
        if TMP_SNAPSHOT_LINK.is_symlink() or not TMP_SNAPSHOT_LINK.exists():
            if TMP_SNAPSHOT_LINK.is_symlink() and TMP_SNAPSHOT_LINK.resolve() != SHM_SNAPSHOT_DIR:
                TMP_SNAPSHOT_LINK.unlink(missing_ok=True)
            if not TMP_SNAPSHOT_LINK.exists():
                TMP_SNAPSHOT_LINK.symlink_to(SHM_SNAPSHOT_DIR)
        return SHM_SNAPSHOT_DIR
    except Exception as err:
        _LOGGER.debug("Fallback para /tmp/leticia_snapshots: %s", err)
        TMP_SNAPSHOT_LINK.mkdir(parents=True, exist_ok=True)
        return TMP_SNAPSHOT_LINK


def _persist_frame_to_ram(
    camera_slug: str,
    room_slug: str,
    frame: bytes,
    force_media: bool = True,
) -> None:
    """Grava o frame JPEG ao vivo em tmpfs (RAM) e atualiza _last.jpg."""
    try:
        ram_dir = _ensure_tmpfs_dirs()
        (ram_dir / f"{camera_slug}.jpg").write_bytes(frame)
        if room_slug:
            room_ram = ram_dir / room_slug
            room_ram.mkdir(parents=True, exist_ok=True)
            (room_ram / "_last.jpg").write_bytes(frame)
            if force_media and MEDIA_SNAPSHOT_DIR.exists():
                media_room = MEDIA_SNAPSHOT_DIR / room_slug
                media_room.mkdir(parents=True, exist_ok=True)
                media_last = media_room / "_last.jpg"
                media_last.write_bytes(frame)
    except Exception as err:
        _LOGGER.debug("Falha ao persistir snapshot em RAM (%s): %s", camera_slug, err)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    await hass.async_add_executor_job(_ensure_tmpfs_dirs)
    coordinator: MwTuyaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[MwTuyaCamera] = []
    idx = 0
    for dev in coordinator.active_devices:
        for spec in infer_entity_specs(dev):
            if spec.platform == "camera":
                entities.append(MwTuyaCamera(coordinator, dev, spec, prewarm_delay=idx * 0.4))
                idx += 1
    async_add_entities(entities)


class MwTuyaCamera(MwTuyaEntity, CameraEntity):
    """Câmera IPC Tuya com RTSP 100% Local LAN e buffer RAM tmpfs em tempo real."""

    _attr_brand = "Tuya"

    def __init__(self, coordinator, device, spec, prewarm_delay: float = 0.0) -> None:
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
        self._stream_denied_until = 0.0
        self._last_image: bytes | None = None
        self._last_image_at = 0.0
        self._prewarm_delay = prewarm_delay
        self._capture_task: asyncio.Task[bytes | None] | None = None

        self._local_cfg = LOCAL_RTSP_MAP.get(self._device_id)
        if self._local_cfg:
            self._camera_slug = self._local_cfg["camera_slug"]
            self._room_slug = self._local_cfg["room_slug"]
        else:
            self._camera_slug = f"camera_{self._device_id[-6:]}"
            self._room_slug = ""

    def _local_rtsp_url(self) -> str | None:
        if not self._local_cfg:
            return None
        dev = self.device_obj
        local_ip = dev.local_ip if dev else None
        ip = (local_ip or self._local_cfg["ip"]).strip()
        if not ip.startswith("192.168.1."):
            ip = self._local_cfg["ip"]
        port = self._local_cfg["port"]
        path = self._local_cfg["path"]
        return f"rtsp://admin:admin@{ip}:{port}{path}"

    async def _async_ensure_local_onvif(self) -> bool:
        """Garante via TCP 6668 (proto 3.4) que o servidor ONVIF/RTSP local da câmera está ativo."""
        if not self._local_cfg:
            return False
        dev = self.device_obj
        local_ip = dev.local_ip if dev else None
        ip = (local_ip or self._local_cfg["ip"]).strip()
        if not ip.startswith("192.168.1."):
            ip = self._local_cfg["ip"]
        onvif_dp = str(self._local_cfg["onvif_dp"])
        client = self.coordinator.local_clients.get(self._device_id)
        if client is None and dev and dev.local_key:
            client = TuyaLocalClient(
                host=ip,
                device_id=self._device_id,
                local_key=dev.local_key,
                version=dev.local_version or "3.4",
            )
            self.coordinator.local_clients[self._device_id] = client
        if client is None:
            return False
        try:
            await client.async_set_dps({onvif_dp: True})
            return True
        except Exception as err:
            _LOGGER.debug("Auto-enable ONVIF local em %s (%s): %s", self.entity_id, ip, err)
            return False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.hass.async_create_background_task(
            self._async_prewarm(),
            f"mw_tuya_camera_prewarm_{self._camera_slug}",
        )

    async def _async_prewarm(self) -> None:
        """Ativa ONVIF local e captura frame real inicial ao vivo em background."""
        if self._prewarm_delay > 0:
            await asyncio.sleep(self._prewarm_delay)
        try:
            await self._async_ensure_local_onvif()
            url = await self.stream_source()
            if url:
                await self._async_capture_from_rtsp(url, timeout=6.0, force_media=True)
                self.async_write_ha_state()
        except Exception as err:
            _LOGGER.debug(
                "Pré-aquecimento da câmera %s concluído com aviso: %s", self.entity_id, err
            )

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
        if not self.is_on:
            return None
        local_url = self._local_rtsp_url()
        if local_url:
            self._stream_url = local_url
            self._stream_at = time.monotonic()
            return local_url

        now = time.monotonic()
        if self._stream_url and now - self._stream_at < STREAM_TTL:
            return self._stream_url
        if now < self._stream_denied_until and self.coordinator.smartlife is None:
            return None
        try:
            url = await self.coordinator.async_stream_url(self._device_id)
        except (TuyaApiError, SmartLifeError) as err:
            if getattr(err, "code", None) in (
                28841101,
                1106,
            ) and self.coordinator.smartlife is None:
                self._stream_denied_until = now + STREAM_RETRY_COOLDOWN
            return self._stream_url
        except Exception:
            return self._stream_url

        if url:
            self._stream_url = url
            self._stream_at = now
            self._stream_denied_until = 0.0
        return self._stream_url

    async def _async_run_ffmpeg(
        self,
        source: str,
        width: int | None = None,
        height: int | None = None,
        timeout: float = 5.5,
    ) -> bytes | None:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-analyzeduration",
            "1000000",
            "-probesize",
            "1000000",
            "-i",
            source,
            "-frames:v",
            "1",
            "-q:v",
            "3",
        ]
        if width and height:
            cmd.extend(["-vf", f"scale={width}:{height}"])
        cmd.extend(["-f", "image2pipe", "-vcodec", "mjpeg", "-"])

        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if stdout and len(stdout) >= 2048 and stdout.startswith(b"\xff\xd8"):
                return stdout
        except TimeoutError:
            if proc is not None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
        except Exception as err:
            _LOGGER.debug("Erro ffmpeg RTSP em %s: %s", self.entity_id, err)
        return None

    async def _async_capture_from_rtsp(
        self,
        source: str,
        width: int | None = None,
        height: int | None = None,
        timeout: float = 5.5,
        force_media: bool = True,
    ) -> bytes | None:
        """Extrai 1 frame JPEG ao vivo via RTSP local (com auto-reparo ONVIF se necessário)."""
        stdout = await self._async_run_ffmpeg(source, width=width, height=height, timeout=timeout)
        if stdout is None and self._local_cfg is not None:
            # Se a câmera reiniciou, reativa o servidor ONVIF local via TCP 6668 e tenta novamente
            await self._async_ensure_local_onvif()
            await asyncio.sleep(0.4)
            stdout = await self._async_run_ffmpeg(
                source, width=width, height=height, timeout=timeout
            )

        if stdout:
            now = time.monotonic()
            self._last_image = stdout
            self._last_image_at = now
            await self.hass.async_add_executor_job(
                _persist_frame_to_ram,
                self._camera_slug,
                self._room_slug,
                stdout,
                force_media,
            )
            return stdout
        return None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        now = time.monotonic()
        if self._last_image and (now - self._last_image_at < IMAGE_CACHE_TTL):
            return self._last_image

        source = await self.stream_source()
        if source:
            if self._capture_task is None or self._capture_task.done():
                self._capture_task = self.hass.async_create_task(
                    self._async_capture_from_rtsp(
                        source, width=width, height=height, timeout=5.5, force_media=True
                    )
                )
            try:
                fresh = await asyncio.wait_for(asyncio.shield(self._capture_task), timeout=7.5)
                if fresh:
                    return fresh
            except TimeoutError:
                pass
            except Exception:
                pass

        # Frame só da sessão atual: nunca reaproveita arquivo capturado há dias.
        if self._last_image and (now - self._last_image_at < 120.0):
            return self._last_image
        return None

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
        attrs["stream_api"] = "ok"
        attrs["stream_channel"] = "local_rtsp" if self._local_cfg else (
            "smartlife" if self.coordinator.smartlife is not None else "openapi"
        )
        attrs["tmpfs_snapshot"] = f"/tmp/leticia_snapshots/{self._camera_slug}.jpg"
        attrs["last_frame_bytes"] = len(self._last_image) if self._last_image else 0
        attrs["last_frame_age_s"] = (
            round(time.monotonic() - self._last_image_at, 1) if self._last_image_at > 0 else None
        )
        return attrs
