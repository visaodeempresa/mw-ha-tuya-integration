"""Coordenador de conta Tuya e Roteador Híbrido Inteligente (Local + Cloud).

Cada `ConfigEntry` representa uma conta Tuya independente e mantém seu próprio
`MwTuyaCoordinator`, permitindo múltiplas contas ativas simultaneamente sem
colisão de tokens, dispositivos ou cenas.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TuyaApiError, TuyaAuthError, TuyaCloudClient
from .const import (
    CONF_ACCOUNT_NAME,
    CONF_LOCAL_HOSTS,
    CONF_LOCAL_VERSIONS,
    CONF_ROUTING_MODE,
    CONF_SCAN_INTERVAL,
    CONF_SELECTED_DEVICES,
    CONF_SELECTED_SCENES,
    CONF_UID,
    DEFAULT_LOCAL_HOSTS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    DP_ALIASES,
    ROUTING_CLOUD_ONLY,
    ROUTING_HYBRID_LOCAL_FIRST,
    ROUTING_LOCAL_ONLY,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from .dpspec import DpSpec, encode_local
from .local import TuyaLocalClient, TuyaLocalError, async_discover_lan_devices
from .models import MwTuyaDevice, MwTuyaScene
from .push import TuyaPushHub, get_hub, status_from_event
from .smartlife import SmartLifeError, SmartLifeSession, raw_from_device, specs_from_device

_LOGGER = logging.getLogger(__name__)

LOCAL_POLL_CONCURRENCY = 8
LOCAL_POLL_TIMEOUT = 4.0
LOCAL_REPROBE_SECONDS = 300


def _msg_cena(scene: MwTuyaScene, err: Exception) -> str:
    """Mensagem amigável para falha de nuvem ao acionar uma cena."""
    return f"Falha ao acionar a cena {scene.name} via nuvem: {err}"


class MwTuyaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Gerencia o catálogo da conta, seleção granular e roteamento híbrido Local/Cloud."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: TuyaCloudClient | None,
        smartlife: SmartLifeSession | None = None,
    ) -> None:
        scan_interval = int(
            entry.options.get(CONF_SCAN_INTERVAL)
            or entry.data.get(CONF_SCAN_INTERVAL)
            or DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=scan_interval),
            config_entry=entry,
        )
        self.client = client
        self.smartlife = smartlife
        # device_ids / scene_ids atendidos pelo canal Smart Life
        self.sl_devices: set[str] = set()
        self.sl_scenes: set[str] = set()
        self._sl_seen: dict[str, dict[str, Any]] = {}
        self.options_snapshot: dict[str, Any] = {}
        self.account_name = str(
            entry.data.get(CONF_ACCOUNT_NAME) or entry.data.get(CONF_UID) or "Conta Tuya"
        )
        self._store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}_{entry.entry_id}")

        # Catálogo completo da conta (todos os devices e cenas descobertos)
        self.catalog_devices: dict[str, MwTuyaDevice] = {}
        self.catalog_scenes: dict[str, MwTuyaScene] = {}
        self.lan_map: dict[str, dict[str, Any]] = {}

        # Clientes TCP locais por device_id (ou gateway_id para sub-devices)
        self.local_clients: dict[str, TuyaLocalClient] = {}
        self.local_ok: dict[str, bool] = {}
        self._local_misses: dict[str, int] = {}
        self._last_probe: dict[str, float] = {}

        # Estatísticas de telemetria híbrida por device_id
        self.stats: dict[str, dict[str, int]] = {}

        # Push em tempo real (Message Service) e ouvintes por device_id
        self._push_hub: TuyaPushHub | None = None
        self._push_listeners: dict[str, set[Callable[[dict[str, Any]], None]]] = {}

    # ------------------------------------------------------------------ Push
    @callback
    def async_add_push_listener(
        self, device_id: str, listener: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        self._push_listeners.setdefault(device_id, set()).add(listener)

        def _remove() -> None:
            self._push_listeners.get(device_id, set()).discard(listener)

        return _remove

    @property
    def push_connected(self) -> bool:
        if self.smartlife is not None:
            return self.smartlife.mq_connected
        return bool(self._push_hub and self._push_hub.connected)

    @callback
    def async_start_push(
        self, session: Any, base_url: str, access_id: str, secret: str
    ) -> Callable[[], None]:
        """Message Service (Pulsar) — só para contas sem o canal Smart Life."""
        self._push_hub = get_hub(session, base_url, access_id, secret)
        return self._push_hub.add_listener(self._on_push_event)

    async def async_start_smartlife_push(self) -> None:
        if self.smartlife is None:
            return
        loop = self.hass.loop

        def _from_thread(did: str, status: dict[str, Any], online: bool | None) -> None:
            loop.call_soon_threadsafe(self._on_push_status, did, status, online)

        await self.hass.async_add_executor_job(self.smartlife.start_push, _from_thread)

    async def async_stop_smartlife(self) -> None:
        if self.smartlife is not None:
            await self.hass.async_add_executor_job(self.smartlife.stop)

    @callback
    def _on_push_event(self, event: dict[str, Any]) -> None:
        did, status, online = status_from_event(event)
        self._on_push_status(did, status, online)

    @callback
    def _on_push_status(self, did: str, status: dict[str, Any], online: bool | None) -> None:
        dev = self.catalog_devices.get(did)
        if dev is None or did not in set(self.selected_device_ids):
            return
        if status:
            dev.merge_cloud_status([{"code": c, "value": v} for c, v in status.items()])
            self._sl_seen.setdefault(did, {}).update(status)
        if online is not None:
            dev.online = online
        self._record_stat(did, "push")
        for listener in list(self._push_listeners.get(did, ())):
            listener(status)
        self.async_set_updated_data(self.data or {})

    # ------------------------------------------------------------------ Opções
    @property
    def selected_device_ids(self) -> list[str]:
        return list(
            self.config_entry.options.get(CONF_SELECTED_DEVICES)
            or self.config_entry.data.get(CONF_SELECTED_DEVICES)
            or []
        )

    @property
    def selected_scene_ids(self) -> list[str]:
        return list(
            self.config_entry.options.get(CONF_SELECTED_SCENES)
            or self.config_entry.data.get(CONF_SELECTED_SCENES)
            or []
        )

    @property
    def routing_mode(self) -> str:
        return str(
            self.config_entry.options.get(CONF_ROUTING_MODE)
            or self.config_entry.data.get(CONF_ROUTING_MODE)
            or ROUTING_HYBRID_LOCAL_FIRST
        )

    @property
    def configured_local_hosts(self) -> dict[str, str]:
        return dict(
            self.config_entry.options.get(CONF_LOCAL_HOSTS)
            or self.config_entry.data.get(CONF_LOCAL_HOSTS)
            or {}
        )

    @property
    def configured_local_versions(self) -> dict[str, str]:
        return dict(
            self.config_entry.options.get(CONF_LOCAL_VERSIONS)
            or self.config_entry.data.get(CONF_LOCAL_VERSIONS)
            or {}
        )

    @property
    def active_devices(self) -> list[MwTuyaDevice]:
        """Retorna apenas os dispositivos explicitamente selecionados pelo usuário."""
        return [
            self.catalog_devices[did]
            for did in self.selected_device_ids
            if did in self.catalog_devices
        ]

    @property
    def active_scenes(self) -> list[MwTuyaScene]:
        """Retorna apenas as cenas explicitamente selecionadas pelo usuário."""
        return [
            self.catalog_scenes[sid]
            for sid in self.selected_scene_ids
            if sid in self.catalog_scenes
        ]

    def _restore_sl_cache(self, cached: dict[str, Any]) -> None:
        """Restaura o cache do canal Smart Life gravado no storage (resiliente a reinícios)."""
        cached_sl_devs = cached.get("sl_devices")
        if isinstance(cached_sl_devs, list):
            self.sl_devices.update(str(x) for x in cached_sl_devs if str(x))
        cached_sl_scenes = cached.get("sl_scenes")
        if isinstance(cached_sl_scenes, list):
            self.sl_scenes.update(str(x) for x in cached_sl_scenes if str(x))

    def _harvest_existing_ha_hosts(self) -> dict[str, dict[str, str]]:
        """Importa IPs e versões de entradas `localtuya` ou `mw_infrared` no HA."""
        harvested: dict[str, dict[str, str]] = {}
        try:
            for lt_entry in self.hass.config_entries.async_entries("localtuya"):
                devs = lt_entry.data.get("devices") or {}
                if isinstance(devs, dict):
                    for did, d in devs.items():
                        ip = str(d.get("host") or "").strip() if isinstance(d, dict) else ""
                        if ip:
                            harvested[str(did)] = {
                                "ip": ip,
                                "version": str(d.get("protocol_version") or "3.3").strip(),
                            }
            for ir_entry in self.hass.config_entries.async_entries("mw_infrared"):
                hosts = (
                    ir_entry.options.get("local_hosts") or ir_entry.data.get("local_hosts") or {}
                )
                if isinstance(hosts, dict):
                    for did, ip in hosts.items():
                        ip_str = str(ip or "").strip()
                        if ip_str:
                            harvested[str(did)] = {"ip": ip_str, "version": "3.3"}
        except Exception as err:
            _LOGGER.debug("Falha ao importar hosts de outras integrações: %s", err)
        return harvested

    # ------------------------------------------------------------------ Catálogo
    async def async_load_catalog(self, scan_lan: bool = True) -> None:
        """Carrega o catálogo da nuvem + cache local + varredura UDP LAN + Shadow v2.0."""
        cached = await self._store.async_load() or {}
        if isinstance(cached.get("lan_map"), dict):
            self.lan_map.update(cached["lan_map"])
        models_cache: dict[str, dict[str, DpSpec]] = {}
        for key, raw_specs in (cached.get("models") or {}).items():
            if isinstance(raw_specs, dict):
                models_cache[key] = {c: DpSpec.from_dict(s) for c, s in raw_specs.items()}

        harvested = self._harvest_existing_ha_hosts()
        for did, info in harvested.items():
            self.lan_map.setdefault(did, info)

        for did, (def_ip, def_ver) in DEFAULT_LOCAL_HOSTS.items():
            self.lan_map.setdefault(did, {"ip": def_ip, "version": def_ver})

        if scan_lan:
            try:
                discovered = await async_discover_lan_devices(timeout=2.0)
                if discovered:
                    self.lan_map.update(discovered)
            except Exception as err:
                _LOGGER.debug("Varredura UDP LAN falhou: %s", err)

        selected_set = set(self.selected_device_ids)
        devices: list[MwTuyaDevice] = []
        scenes: list[MwTuyaScene] = []
        if self.client is not None:
            try:
                devices = await self.client.async_list_devices(self.lan_map)
                scenes = await self.client.async_list_scenes()
            except (TuyaApiError, TuyaAuthError) as err:
                if self.smartlife is None and not cached.get("devices"):
                    raise
                _LOGGER.warning(
                    "MW Tuya [%s]: OpenAPI indisponível (%s), utilizando catálogo local em cache",
                    self.account_name,
                    err,
                )

        # Canal Smart Life: aparelhos, status, local_key, specs e cenas
        sl_specs: dict[str, dict[str, DpSpec]] = {}
        if self.smartlife is not None:
            # Sobrevive a reinícios do HA: o cache do canal (sem cota OpenAPI 60001001)
            # volta antes do load; só é descartado após uma carga completa bem-sucedida.
            self._restore_sl_cache(cached)
            sl = self.smartlife
            try:
                await self.hass.async_add_executor_job(sl.load, selected_set)
                self.sl_devices.clear()
                self.sl_scenes.clear()
                by_id = {d.device_id: d for d in devices}
                for did, sdev in sl.devices.items():
                    raw = raw_from_device(sdev)
                    if did in by_id:
                        dev = by_id[did]
                        dev.online = raw["online"]
                        if raw["local_key"]:
                            dev.local_key = raw["local_key"]
                        dev.merge_cloud_status(raw["status"])
                    else:
                        dev = MwTuyaDevice.from_api(raw, self.lan_map.get(did))
                        devices.append(dev)
                        by_id[did] = dev
                    self.sl_devices.add(did)
                    if did in selected_set:
                        sl_specs[did] = specs_from_device(sdev)
                homes = sl.homes()
                sl_scene_list = await self.hass.async_add_executor_job(sl.scenes)
                known = {s.scene_id for s in scenes}
                for item in sl_scene_list:
                    sid = str(getattr(item, "scene_id", "") or "")
                    if not sid:
                        continue
                    self.sl_scenes.add(sid)
                    if sid in known:
                        continue
                    home_id = str(getattr(item, "home_id", "") or "")
                    scenes.append(
                        MwTuyaScene(
                            scene_id=sid,
                            name=str(getattr(item, "name", "") or sid).strip(),
                            home_id=home_id,
                            home_name=homes.get(home_id, ""),
                            enabled=bool(getattr(item, "enabled", True)),
                        )
                    )
            except Exception as err:
                _LOGGER.warning(
                    "MW Tuya [%s]: falha parcial no catálogo Smart Life: %s",
                    self.account_name,
                    err,
                )
            devices.sort(key=lambda d: d.name.lower())
            scenes.sort(key=lambda s: s.name.lower())

        # Sobrevivência a reinícios durante indisponibilidade total da nuvem (ou estouro de cota)
        if not devices and isinstance(cached.get("devices"), dict):
            for did, raw_d in cached["devices"].items():
                devices.append(MwTuyaDevice.from_api(raw_d, self.lan_map.get(did)))
            _LOGGER.info(
                "MW Tuya [%s]: nuvem indisponível, %d dispositivos recuperados do cache",
                self.account_name,
                len(devices),
            )
        if not scenes and isinstance(cached.get("scenes"), dict):
            for raw_s in cached["scenes"].values():
                scenes.append(MwTuyaScene.from_dict(raw_s))

        hosts_override = self.configured_local_hosts
        versions_override = self.configured_local_versions

        self.catalog_devices.clear()
        self.local_clients.clear()

        for dev in devices:
            if dev.device_id in hosts_override and hosts_override[dev.device_id].strip():
                dev.local_ip = hosts_override[dev.device_id].strip()
            if dev.device_id in versions_override and versions_override[dev.device_id].strip():
                dev.local_version = versions_override[dev.device_id].strip()
            self.catalog_devices[dev.device_id] = dev

        selected_devs = [d for d in devices if d.device_id in selected_set]

        # Thing Model (OpenAPI): 1 chamada por produto (cache persistente)
        for dev in selected_devs:
            key = dev.product_id or dev.device_id
            if key not in models_cache:
                models_cache[key] = {}
        missing = [
            next(d for d in selected_devs if (d.product_id or d.device_id) == key)
            for key, specs in models_cache.items()
            if not specs and any((d.product_id or d.device_id) == key for d in selected_devs)
        ]
        if self.client is not None and missing:
            try:
                fetched = await asyncio.gather(
                    *(self.client.async_get_thing_model(d.device_id) for d in missing),
                    return_exceptions=True,
                )
                for dev, specs in zip(missing, fetched, strict=True):
                    if isinstance(specs, dict) and specs:
                        models_cache[dev.product_id or dev.device_id] = specs
            except Exception as err:
                _LOGGER.debug(
                    "MW Tuya [%s]: Thing Model OpenAPI indisponível (%s)",
                    self.account_name,
                    err,
                )
        models_cache = {k: v for k, v in models_cache.items() if v}

        # Shadow (valores + nomes personalizados dos canais) em paralelo
        if self.client is not None:
            try:
                raw_shadows = await asyncio.gather(
                    *(self.client.async_get_shadow_properties(d.device_id) for d in selected_devs),
                    return_exceptions=True,
                )
                shadows = [s if isinstance(s, list) else [] for s in raw_shadows]
            except Exception as err:
                _LOGGER.debug(
                    "MW Tuya [%s]: Shadow OpenAPI indisponível (%s)",
                    self.account_name,
                    err,
                )
                shadows = [[] for _ in selected_devs]
        else:
            shadows = [[] for _ in selected_devs]
        for dev, props in zip(selected_devs, shadows, strict=True):
            model = models_cache.get(dev.product_id or dev.device_id) or {}
            # Thing Model é a fonte da verdade; sem ele, a spec do Smart Life
            dev.apply_thing_model(model or sl_specs.get(dev.device_id) or {})
            for code, spec in (sl_specs.get(dev.device_id) or {}).items():
                if spec.dp_id is not None and code not in dev.dp_map:
                    dev.dp_map[code] = spec.dp_id
            if props:
                dev.apply_shadow_properties(props)
            if dev.is_local_configured:
                self.local_clients[dev.device_id] = TuyaLocalClient(
                    host=dev.local_ip,
                    device_id=dev.device_id,
                    local_key=dev.local_key,
                    version=dev.local_version,
                )
                self.local_ok.setdefault(dev.device_id, True)

        self.catalog_scenes = {s.scene_id: s for s in scenes}

        await self._store.async_save(
            {
                "lan_map": self.lan_map,
                "devices": {k: v.to_dict() for k, v in self.catalog_devices.items()},
                "scenes": {k: v.to_dict() for k, v in self.catalog_scenes.items()},
                "sl_devices": sorted(self.sl_devices),
                "sl_scenes": sorted(self.sl_scenes),
                "models": {
                    k: {c: s.to_dict() for c, s in v.items()} for k, v in models_cache.items()
                },
            }
        )
        _LOGGER.info(
            "MW Tuya [%s]: catálogo (%d devices, %d ativos, %d cenas, %d ativas, %d locais)",
            self.account_name,
            len(self.catalog_devices),
            len(self.active_devices),
            len(self.catalog_scenes),
            len(self.active_scenes),
            len(self.local_clients),
        )

    # ------------------------------------------------------------------ Atualização
    async def _async_update_data(self) -> dict[str, Any]:
        """Atualiza estado combinando leitura Cloud em lote e leitura Local TCP."""
        selected = set(self.selected_device_ids)
        routing = self.routing_mode

        # 0. Smart Life: o SDK mantém o status vivo via MQTT — só copia da memória
        if self.smartlife is not None and routing != ROUTING_LOCAL_ONLY:
            for did in selected & self.sl_devices:
                sdev = self.smartlife.devices.get(did)
                dev = self.catalog_devices.get(did)
                if sdev is None or dev is None:
                    continue
                dev.online = bool(getattr(sdev, "online", dev.online))
                seen = self._sl_seen.setdefault(did, {})
                changed = {
                    k: v for k, v in (sdev.status or {}).items() if k not in seen or seen[k] != v
                }
                if changed:
                    dev.merge_cloud_status(changed)
                    seen.update(changed)

        # 1. Atualiza estado da nuvem em 1 única chamada por conta (econômico em QPS)
        sl_mqtt_alive = bool(self.smartlife is not None and self.smartlife.mq_connected)
        needs_openapi = bool(selected - self.sl_devices) or not sl_mqtt_alive
        if routing != ROUTING_LOCAL_ONLY and self.client is not None and needs_openapi:
            try:
                raw_devices = await self.client.async_list_raw_devices()
                for raw in raw_devices:
                    did = str(raw.get("id") or "")
                    if not did:
                        continue
                    if did in self.catalog_devices:
                        dev = self.catalog_devices[did]
                        dev.online = bool(raw.get("online", dev.online))
                        if raw.get("local_key"):
                            dev.local_key = str(raw["local_key"])
                        dev.merge_cloud_status(raw.get("status") or [])
                    else:
                        self.catalog_devices[did] = MwTuyaDevice.from_api(
                            raw, self.lan_map.get(did)
                        )
            except TuyaAuthError as err:
                if routing == ROUTING_CLOUD_ONLY:
                    raise UpdateFailed(
                        f"Credenciais Tuya recusadas ({self.account_name}): {err}"
                    ) from err
                _LOGGER.debug(
                    "MW Tuya [%s]: credenciais de nuvem recusadas (%s), mantendo operação local",
                    self.account_name,
                    err,
                )
            except TuyaApiError as err:
                if routing == ROUTING_CLOUD_ONLY:
                    raise UpdateFailed(
                        f"Tuya Cloud indisponível ({self.account_name}): {err}"
                    ) from err
                _LOGGER.debug(
                    "MW Tuya [%s]: nuvem indisponível (%s), mantendo operação local",
                    self.account_name,
                    err,
                )
            except Exception as err:
                if routing == ROUTING_CLOUD_ONLY:
                    raise UpdateFailed(
                        f"Erro inesperado na nuvem ({self.account_name}): {err}"
                    ) from err
                _LOGGER.debug(
                    "MW Tuya [%s]: falha na leitura da nuvem (%s), mantendo operação local",
                    self.account_name,
                    err,
                )

        # 2. Leitura local em paralelo (limite de conexões e timeout curto por aparelho)
        if routing != ROUTING_CLOUD_ONLY:
            sem = asyncio.Semaphore(LOCAL_POLL_CONCURRENCY)
            await asyncio.gather(
                *(self._async_poll_local(did, sem) for did in selected if did in self.local_clients)
            )
        return {
            "devices": {
                did: self.catalog_devices[did] for did in selected if did in self.catalog_devices
            },
            "scenes": {
                sid: self.catalog_scenes[sid]
                for sid in self.selected_scene_ids
                if sid in self.catalog_scenes
            },
        }

    async def _async_poll_local(self, did: str, sem: asyncio.Semaphore) -> None:
        """Lê os DPs locais de um aparelho; 3 falhas seguidas → só nuvem até a sonda voltar."""
        dev = self.catalog_devices.get(did)
        client = self.local_clients.get(did)
        if not dev or not client:
            return
        now = time.monotonic()
        async with sem:
            if not self.local_ok.get(did, True):
                if now - self._last_probe.get(did, 0.0) < LOCAL_REPROBE_SECONDS:
                    return
                self._last_probe[did] = now
                try:
                    alive = await asyncio.wait_for(client.async_ping(), LOCAL_POLL_TIMEOUT)
                except (TimeoutError, TuyaLocalError, OSError):
                    alive = False
                if not alive:
                    return
                self.local_ok[did] = True
                self._local_misses[did] = 0
            try:
                dps = await asyncio.wait_for(
                    client.async_get_dps(node_id=dev.node_id), LOCAL_POLL_TIMEOUT
                )
            except (TimeoutError, TuyaLocalError, OSError):
                dps = None
        if dps:
            dev.merge_local_dps(dps)
            dev.online = True
            self._local_misses[did] = 0
            return
        misses = self._local_misses.get(did, 0) + 1
        self._local_misses[did] = misses
        if misses >= 3:
            self.local_ok[did] = False
            self._last_probe[did] = now

    # ------------------------------------------------------------------ Roteador Híbrido
    async def async_send_device_command(
        self,
        device_id: str,
        code: str,
        value: Any,
        dp_id: int | None = None,
    ) -> str:
        """Compat: envia um único DP (ver `async_send_device_commands`)."""
        dev = self.catalog_devices.get(device_id)
        if dev and dp_id is not None and dev.resolve_dp_id(code) is None:
            dev.dp_map[code] = int(dp_id)
        return await self.async_send_device_commands(device_id, {code: value})

    async def async_send_device_commands(self, device_id: str, commands: dict[str, Any]) -> str:
        """Envia vários DPs com chaveamento inteligente e transparente entre Local e Cloud.

        Em modo hybrid_local_first:
        1. Tenta envio direto Local via TCP 6668 (com auto-recuperação de versão).
        2. Se Local falhar ou não estiver disponível, chaveia de forma transparente para Nuvem.
        3. Se a Nuvem falhar (ex: estouro de cota [60001001], offline, timeout) e houver rota local,
           chaveia imediatamente de volta para acesso Local direto.
        4. O chaveamento de canal é tratado como operacional (log DEBUG, zero ruído de IO).
        """
        dev = self.catalog_devices.get(device_id)
        if not dev:
            raise HomeAssistantError(
                f"Dispositivo {device_id} não encontrado na conta {self.account_name}"
            )
        if not commands:
            return "noop"

        # Auto-provisionamento de host/versão se ausente no objeto do dispositivo
        if not dev.local_ip:
            lan_info = self.lan_map.get(device_id) or {}
            def_ip, def_ver = DEFAULT_LOCAL_HOSTS.get(device_id, ("", "3.3"))
            if lan_info.get("ip"):
                dev.local_ip = str(lan_info["ip"])
                dev.local_version = str(lan_info.get("version") or def_ver)
            elif def_ip:
                dev.local_ip = str(def_ip)
                dev.local_version = str(def_ver)

        routing = self.routing_mode
        local_client = self.local_clients.get(device_id)
        if local_client is None and dev.is_local_configured:
            local_client = TuyaLocalClient(
                host=dev.local_ip,
                device_id=dev.device_id,
                local_key=dev.local_key,
                version=dev.local_version,
            )
            self.local_clients[device_id] = local_client
            self.local_ok.setdefault(device_id, True)

        dps: dict[str, Any] = {}
        for code, value in commands.items():
            dp = dev.resolve_dp_id(code)
            if dp is None:
                dps = {}
                break
            dps[str(dp)] = encode_local(code, value, dev.local_hex_len.get(code))

        can_try_local = (
            routing != ROUTING_CLOUD_ONLY
            and local_client is not None
            and bool(dps)
        )

        local_attempted = False
        local_err: Exception | None = None

        # 1. Rota Local Primária
        if can_try_local and local_client is not None:
            local_attempted = True
            try:
                if await local_client.async_set_dps(dps, node_id=dev.node_id):
                    self._record_stat(device_id, "local_ok")
                    self._local_misses[device_id] = 0
                    self.local_ok[device_id] = True
                    dev.status.update(commands)
                    for c, v in commands.items():
                        for alias in DP_ALIASES.get(c, ()):
                            dev.status[alias] = v
                    self.async_set_updated_data(self.data or {})
                    return "local"
            except TuyaLocalError as err:
                local_err = err
                self._record_stat(device_id, "local_fail")
                misses = self._local_misses.get(device_id, 0) + 1
                self._local_misses[device_id] = misses
                if misses >= 3:
                    self.local_ok[device_id] = False
                if routing == ROUTING_LOCAL_ONLY:
                    raise HomeAssistantError(
                        f"Falha no envio local para {dev.name} ({dev.local_ip}): {err}"
                    ) from err
                _LOGGER.debug(
                    "MW Tuya [%s]: chaveamento para %s (%s) — Local falhou (%s), chaveando Cloud",
                    self.account_name,
                    dev.name,
                    dev.local_ip,
                    err,
                )

        if routing == ROUTING_LOCAL_ONLY:
            raise HomeAssistantError(
                f"Dispositivo {dev.name} está em modo local_only mas não possui rota local ativa."
            )

        # 2. Rota de Nuvem (Smart Life ou OpenAPI)
        payload = []
        for c, v in commands.items():
            target_code = c
            if dev.specs and c not in dev.specs:
                for alias in DP_ALIASES.get(c, ()):
                    if alias in dev.specs:
                        target_code = alias
                        break
            payload.append({"code": target_code, "value": v})

        cloud_err: Exception | None = None
        try:
            if self.smartlife is not None and device_id in self.sl_devices:
                try:
                    await self.hass.async_add_executor_job(
                        self.smartlife.send, device_id, payload
                    )
                except SmartLifeError:
                    if self.client is None:
                        raise
                    await self.client.async_send_commands(device_id, payload)
            elif self.client is not None:
                await self.client.async_send_commands(device_id, payload)
            else:
                cloud_err = HomeAssistantError(f"{dev.name} sem rota de nuvem disponível")
        except (SmartLifeError, TuyaApiError, TuyaAuthError, Exception) as err:
            cloud_err = err

        if cloud_err is None:
            route = "cloud_fallback" if local_attempted else "cloud"
            self._record_stat(device_id, route)
            dev.status.update(commands)
            for c, v in commands.items():
                for alias in DP_ALIASES.get(c, ()):
                    dev.status[alias] = v
            self.async_set_updated_data(self.data or {})
            return route

        # 3. Chaveamento de canal reverso: Nuvem falhou (ex: cota 60001001 / offline / timeout).
        # Se possuir cliente e mapa de DPs locais, tenta o acesso direto Local.
        if local_client is not None and bool(dps):
            _LOGGER.debug(
                "MW Tuya [%s]: chaveamento reverso para %s — Nuvem falhou (%s), ativando Local",
                self.account_name,
                dev.name,
                cloud_err,
            )
            try:
                if await local_client.async_set_dps(dps, node_id=dev.node_id):
                    self._record_stat(device_id, "local_fallback")
                    self._local_misses[device_id] = 0
                    self.local_ok[device_id] = True
                    dev.status.update(commands)
                    for c, v in commands.items():
                        for alias in DP_ALIASES.get(c, ()):
                            dev.status[alias] = v
                    self.async_set_updated_data(self.data or {})
                    return "local_fallback"
            except TuyaLocalError as lerr:
                local_err = lerr
                _LOGGER.debug(
                    "MW Tuya [%s]: acesso local reverso após falha de nuvem para %s falhou: %s",
                    self.account_name,
                    dev.name,
                    lerr,
                )

        _LOGGER.debug(
            "MW Tuya [%s]: comando para %s sem sucesso em ambos os canais (nuvem=%s, local=%s)",
            self.account_name,
            dev.name,
            cloud_err,
            local_err,
        )
        is_quota = "60001001" in str(cloud_err) or "quota" in str(cloud_err).lower()
        if is_quota:
            raise HomeAssistantError(
                f"Cota Tuya esgotada ({cloud_err}) e acesso Local indisponível para "
                f"{dev.name} ({dev.local_ip or 'sem IP'})"
            ) from cloud_err
        raise HomeAssistantError(
            f"Falha ao enviar comando para {dev.name} via Nuvem e Local: {cloud_err}"
        ) from cloud_err
        for c, v in commands.items():
            for alias in DP_ALIASES.get(c, ()):
                dev.status[alias] = v
        self.async_set_updated_data(self.data or {})
        return route

    async def async_trigger_scene(self, scene_id: str) -> bool:
        """Aciona uma cena Tap-to-Run na nuvem Tuya."""
        scene = self.catalog_scenes.get(scene_id)
        if not scene:
            raise HomeAssistantError(f"Cena {scene_id} não encontrada na conta {self.account_name}")
        if self.smartlife is not None and scene_id in self.sl_scenes:
            try:
                await self.hass.async_add_executor_job(
                    self.smartlife.trigger_scene, scene.home_id, scene.scene_id
                )
                return True
            except Exception:
                if self.client is None:
                    raise
                try:
                    return await self.client.async_trigger_scene(scene.home_id, scene.scene_id)
                except (TuyaApiError, TuyaAuthError) as err:
                    raise HomeAssistantError(_msg_cena(scene, err)) from err
        if self.client is None:
            raise HomeAssistantError(f"Cena {scene.name} sem rota de nuvem disponível")
        try:
            return await self.client.async_trigger_scene(scene.home_id, scene.scene_id)
        except (TuyaApiError, TuyaAuthError) as err:
            raise HomeAssistantError(_msg_cena(scene, err)) from err

    async def async_stream_url(self, device_id: str) -> str | None:
        """URL RTSP da câmera: Smart Life (sem assinatura extra) ou OpenAPI."""
        if self.smartlife is not None:
            try:
                url = await self.hass.async_add_executor_job(
                    self.smartlife.stream_url, device_id, "rtsp"
                )
                if url:
                    return url
            except Exception as err:
                _LOGGER.debug("Smart Life stream_url falhou para %s: %s", device_id, err)
        if self.client is None:
            return None
        res = await self.client.async_post(
            f"/v1.0/devices/{device_id}/stream/actions/allocate", {"type": "rtsp"}
        )
        return res.get("url") if isinstance(res, dict) else None

    def _record_stat(self, device_id: str, key: str) -> None:
        bucket = self.stats.setdefault(device_id, {})
        bucket[key] = bucket.get(key, 0) + 1
