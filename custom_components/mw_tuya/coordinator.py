"""Coordenador de conta Tuya e Roteador Híbrido Inteligente (Local + Cloud).

Cada `ConfigEntry` representa uma conta Tuya independente e mantém seu próprio
`MwTuyaCoordinator`, permitindo múltiplas contas ativas simultaneamente sem
colisão de tokens, dispositivos ou cenas.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
from .local import TuyaLocalClient, TuyaLocalError, async_discover_lan_devices
from .models import MwTuyaDevice, MwTuyaScene

_LOGGER = logging.getLogger(__name__)


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

        # Estatísticas de telemetria híbrida por device_id
        self.stats: dict[str, dict[str, int]] = {}

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

            if dev.device_id in selected_set:
                props = await self.client.async_get_shadow_properties(dev.device_id)
                if props:
                    dev.apply_shadow_properties(props)

            self.catalog_devices[dev.device_id] = dev
            if dev.is_local_configured and dev.device_id in selected_set:
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

        # 2. Para dispositivos selecionados com canal local, consulta DPs locais se necessário
        if routing != ROUTING_CLOUD_ONLY:
            for did in selected:
                dev = self.catalog_devices.get(did)
                local_client = self.local_clients.get(did)
                if not dev or not local_client:
                    continue
                if not self.local_ok.get(did, True):
                    # Sonda recuperação do canal local
                    alive = await local_client.async_ping()
                    self.local_ok[did] = alive
                    if alive:
                        self._local_misses[did] = 0
                if self.local_ok.get(did, False):
                    try:
                        dps = await local_client.async_get_dps(node_id=dev.node_id)
                        if dps:
                            dev.merge_local_dps(dps)
                            dev.online = True
                    except TuyaLocalError:
                        # Não derruba na primeira falha de leitura; apenas comandos contam misses
                        pass

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

    # ------------------------------------------------------------------ Roteador Híbrido
    async def async_send_device_command(
        self,
        device_id: str,
        code: str,
        value: Any,
        dp_id: int | None = None,
    ) -> str:
        """Envia comando ao dispositivo priorizando Local (TCP 6668) com Fallback Cloud.

        Retorna a rota efetivamente utilizada: `"local"`, `"cloud_fallback"` ou `"cloud"`.
        """
        dev = self.catalog_devices.get(device_id)
        if not dev:
            raise HomeAssistantError(
                f"Dispositivo {device_id} não encontrado na conta {self.account_name}"
            )

        routing = self.routing_mode
        resolved_dp = dp_id if dp_id is not None else dev.resolve_dp_id(code)
        local_client = self.local_clients.get(device_id)

        can_try_local = (
            routing != ROUTING_CLOUD_ONLY
            and local_client is not None
            and resolved_dp is not None
            and self.local_ok.get(device_id, True)
        )

        if can_try_local and local_client is not None and resolved_dp is not None:
            try:
                ok = await local_client.async_set_dps(
                    {str(resolved_dp): value}, node_id=dev.node_id
                )
                if ok:
                    self._record_stat(device_id, "local_ok")
                    self._local_misses[device_id] = 0
                    dev.status[code] = value
                    dev.raw_dps[resolved_dp] = value
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
                    "MW Tuya [%s]: envio local para %s (%s) falhou (%s); acionando fallback Cloud",
                    self.account_name,
                    dev.name,
                    dev.local_ip,
                    err,
                )

        if routing == ROUTING_LOCAL_ONLY:
            raise HomeAssistantError(
                f"Dispositivo {dev.name} está em modo local_only mas não possui rota local ativa."
            )

        # Envio Cloud (direto ou fallback)
        await self.client.async_send_commands(device_id, [{"code": code, "value": value}])
        route = "cloud_fallback" if can_try_local else "cloud"
        self._record_stat(device_id, route)
        dev.status[code] = value
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
