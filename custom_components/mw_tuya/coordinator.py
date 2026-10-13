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
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
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

_LOGGER = logging.getLogger(__name__)

LOCAL_POLL_CONCURRENCY = 8
LOCAL_POLL_TIMEOUT = 4.0
LOCAL_REPROBE_SECONDS = 300


class MwTuyaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Gerencia o catálogo da conta, seleção granular e roteamento híbrido Local/Cloud."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: TuyaCloudClient,
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
    @property
    def push_connected(self) -> bool:
        return bool(self._push_hub and self._push_hub.connected)

    @callback
    def async_add_push_listener(
        self, device_id: str, listener: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        self._push_listeners.setdefault(device_id, set()).add(listener)

        def _remove() -> None:
            self._push_listeners.get(device_id, set()).discard(listener)

        return _remove

    @callback
    def async_start_push(
        self, session: Any, base_url: str, access_id: str, secret: str
    ) -> Callable[[], None]:
        self._push_hub = get_hub(session, base_url, access_id, secret)
        return self._push_hub.add_listener(self._on_push_event)

    @callback
    def _on_push_event(self, event: dict[str, Any]) -> None:
        did, status, online = status_from_event(event)
        dev = self.catalog_devices.get(did)
        if dev is None or did not in set(self.selected_device_ids):
            return
        if status:
            dev.merge_cloud_status([{"code": c, "value": v} for c, v in status.items()])
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

    def _harvest_existing_ha_hosts(self) -> dict[str, dict[str, str]]:
        """Importa IPs e versões de entradas `localtuya` ou `mw_infrared` no HA."""
        harvested: dict[str, dict[str, str]] = {}
        try:
            for lt_entry in self.hass.config_entries.async_entries("localtuya"):
                devs = lt_entry.data.get("devices") or {}
                if isinstance(devs, dict):
                    for did, d in devs.items():
                        if isinstance(d, dict) and d.get("host"):
                            harvested[str(did)] = {
                                "ip": str(d["host"]).strip(),
                                "version": str(d.get("protocol_version") or "3.3").strip(),
                            }
            for ir_entry in self.hass.config_entries.async_entries("mw_infrared"):
                hosts = (
                    ir_entry.options.get("local_hosts") or ir_entry.data.get("local_hosts") or {}
                )
                if isinstance(hosts, dict):
                    for did, ip in hosts.items():
                        if ip:
                            harvested[str(did)] = {"ip": str(ip).strip(), "version": "3.3"}
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

        if scan_lan:
            try:
                discovered = await async_discover_lan_devices(timeout=2.0)
                if discovered:
                    self.lan_map.update(discovered)
            except Exception as err:
                _LOGGER.debug("Varredura UDP LAN falhou: %s", err)

        devices = await self.client.async_list_devices(self.lan_map)
        scenes = await self.client.async_list_scenes()

        hosts_override = self.configured_local_hosts
        versions_override = self.configured_local_versions
        selected_set = set(self.selected_device_ids)

        self.catalog_devices.clear()
        self.local_clients.clear()

        for dev in devices:
            if dev.device_id in hosts_override and hosts_override[dev.device_id].strip():
                dev.local_ip = hosts_override[dev.device_id].strip()
            if dev.device_id in versions_override and versions_override[dev.device_id].strip():
                dev.local_version = versions_override[dev.device_id].strip()
            self.catalog_devices[dev.device_id] = dev

        selected_devs = [d for d in devices if d.device_id in selected_set]

        # Thing Model: 1 chamada por produto (cache persistente)
        for dev in selected_devs:
            key = dev.product_id or dev.device_id
            if key not in models_cache:
                models_cache[key] = {}
        missing = [
            next(d for d in selected_devs if (d.product_id or d.device_id) == key)
            for key, specs in models_cache.items()
            if not specs and any((d.product_id or d.device_id) == key for d in selected_devs)
        ]
        fetched = await asyncio.gather(
            *(self.client.async_get_thing_model(d.device_id) for d in missing)
        )
        for dev, specs in zip(missing, fetched, strict=True):
            if specs:
                models_cache[dev.product_id or dev.device_id] = specs
        models_cache = {k: v for k, v in models_cache.items() if v}

        # Shadow (valores + nomes personalizados dos canais) em paralelo
        shadows = await asyncio.gather(
            *(self.client.async_get_shadow_properties(d.device_id) for d in selected_devs)
        )
        for dev, props in zip(selected_devs, shadows, strict=True):
            dev.apply_thing_model(models_cache.get(dev.product_id or dev.device_id) or {})
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

        # 1. Atualiza estado da nuvem em 1 única chamada por conta (econômico em QPS)
        if routing != ROUTING_LOCAL_ONLY:
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
                raise UpdateFailed(
                    f"Credenciais Tuya recusadas ({self.account_name}): {err}"
                ) from err
            except TuyaApiError as err:
                if routing == ROUTING_CLOUD_ONLY:
                    raise UpdateFailed(
                        f"Tuya Cloud indisponível ({self.account_name}): {err}"
                    ) from err
                _LOGGER.warning(
                    "MW Tuya [%s]: nuvem indisponível (%s), mantendo operação local",
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
        """Envia vários DPs priorizando Local (um único frame TCP 6668) com fallback Cloud.

        Só vai local se TODOS os códigos tiverem `dp_id` conhecido — nunca chuta DP.
        Retorna a rota usada: `"local"`, `"cloud_fallback"` ou `"cloud"`.
        """
        dev = self.catalog_devices.get(device_id)
        if not dev:
            raise HomeAssistantError(
                f"Dispositivo {device_id} não encontrado na conta {self.account_name}"
            )
        if not commands:
            return "noop"

        routing = self.routing_mode
        local_client = self.local_clients.get(device_id)
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
            and self.local_ok.get(device_id, True)
        )

        if can_try_local and local_client is not None:
            try:
                if await local_client.async_set_dps(dps, node_id=dev.node_id):
                    self._record_stat(device_id, "local_ok")
                    self._local_misses[device_id] = 0
                    dev.status.update(commands)
                    self.async_set_updated_data(self.data or {})
                    return "local"
            except TuyaLocalError as err:
                self._record_stat(device_id, "local_fail")
                misses = self._local_misses.get(device_id, 0) + 1
                self._local_misses[device_id] = misses
                if misses >= 3:
                    self.local_ok[device_id] = False
                if routing == ROUTING_LOCAL_ONLY:
                    raise HomeAssistantError(
                        f"Falha no envio local para {dev.name} ({dev.local_ip}): {err}"
                    ) from err
                _LOGGER.info(
                    "MW Tuya [%s]: envio local para %s (%s) falhou (%s); fallback Cloud",
                    self.account_name,
                    dev.name,
                    dev.local_ip,
                    err,
                )

        if routing == ROUTING_LOCAL_ONLY:
            raise HomeAssistantError(
                f"Dispositivo {dev.name} está em modo local_only mas não possui rota local ativa."
            )

        await self.client.async_send_commands(
            device_id, [{"code": c, "value": v} for c, v in commands.items()]
        )
        route = "cloud_fallback" if can_try_local else "cloud"
        self._record_stat(device_id, route)
        dev.status.update(commands)
        self.async_set_updated_data(self.data or {})
        return route

    async def async_trigger_scene(self, scene_id: str) -> bool:
        """Aciona uma cena Tap-to-Run na nuvem Tuya."""
        scene = self.catalog_scenes.get(scene_id)
        if not scene:
            raise HomeAssistantError(f"Cena {scene_id} não encontrada na conta {self.account_name}")
        return await self.client.async_trigger_scene(scene.home_id, scene.scene_id)

    def _record_stat(self, device_id: str, key: str) -> None:
        bucket = self.stats.setdefault(device_id, {})
        bucket[key] = bucket.get(key, 0) + 1


class HomeAssistantError(RuntimeError):
    """Erro operacional reportado ao Home Assistant."""
