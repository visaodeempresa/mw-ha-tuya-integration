"""MW Tuya Integration — controle híbrido Local & Cloud multi-conta no Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TuyaApiError, TuyaAuthError, TuyaCloudClient
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_REGION,
    CONF_SMARTLIFE,
    CONF_UID,
    DOMAIN,
    REGIONS,
)
from .coordinator import MwTuyaCoordinator
from .services import async_setup_services, async_unload_services
from .smartlife import SmartLifeSession

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.EVENT,
    Platform.FAN,
    Platform.HUMIDIFIER,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SCENE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SIREN,
    Platform.SWITCH,
    Platform.VACUUM,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = entry.data
    region = str(data.get(CONF_REGION) or "us")
    base_url = REGIONS.get(region, REGIONS["us"])
    session = async_get_clientsession(hass)
    client: TuyaCloudClient | None = None
    if data.get(CONF_CLIENT_ID) and data.get(CONF_CLIENT_SECRET):
        client = TuyaCloudClient(
            session,
            base_url,
            data[CONF_CLIENT_ID],
            data[CONF_CLIENT_SECRET],
            data.get(CONF_UID, ""),
        )
    smartlife = await _async_smartlife_session(hass, entry)
    if client is None and smartlife is None:
        raise ConfigEntryAuthFailed("Conta sem credenciais OpenAPI nem Smart Life")

    coordinator = MwTuyaCoordinator(hass, entry, client, smartlife)
    try:
        await coordinator.async_load_catalog(scan_lan=True)
    except TuyaAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except TuyaApiError as err:
        raise ConfigEntryNotReady(f"Tuya Cloud indisponível: {err}") from err
    except Exception as err:
        if smartlife is None:
            raise
        raise ConfigEntryNotReady(f"Smart Life indisponível: {err}") from err

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    coordinator.options_snapshot = dict(entry.options)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if smartlife is not None:
        await coordinator.async_start_smartlife_push()
    if client is not None and not coordinator.push_connected:
        entry.async_on_unload(
            coordinator.async_start_push(
                session, base_url, data[CONF_CLIENT_ID], data[CONF_CLIENT_SECRET]
            )
        )
    async_setup_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


def _load_smartlife_from_storage(hass: HomeAssistant, entry_id: str) -> dict | None:
    """Carrega credenciais smartlife de .storage/core.config_entries caso injetadas em disco."""
    import json
    from pathlib import Path

    try:
        storage_path = Path(hass.config.path(".storage", "core.config_entries"))
        if not storage_path.exists():
            return None
        raw = json.loads(storage_path.read_text(encoding="utf-8"))
        for item in raw.get("data", {}).get("entries", []):
            if item.get("entry_id") == entry_id:
                sl = (item.get("data") or {}).get(CONF_SMARTLIFE)
                if isinstance(sl, dict) and sl.get("token_info"):
                    return sl
    except Exception as err:
        _LOGGER.debug("Não foi possível ler smartlife do storage em disco: %s", err)
    return None


async def _async_smartlife_session(
    hass: HomeAssistant, entry: ConfigEntry
) -> SmartLifeSession | None:
    sl_data = entry.data.get(CONF_SMARTLIFE)
    if not sl_data:
        sl_data = await hass.async_add_executor_job(
            _load_smartlife_from_storage, hass, entry.entry_id
        )
        if sl_data:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_SMARTLIFE: sl_data}
            )
    if not sl_data:
        return None

    def _on_token(token_info: dict) -> None:
        @callback
        def _save() -> None:
            current = dict(entry.data.get(CONF_SMARTLIFE) or {})
            merged_token = {**dict(current.get("token_info") or {}), **token_info}
            current["token_info"] = merged_token
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_SMARTLIFE: current}
            )

        hass.loop.call_soon_threadsafe(_save)

    return await hass.async_add_executor_job(SmartLifeSession, dict(sl_data), _on_token)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator is not None:
            await coordinator.async_stop_smartlife()
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN, None)
            async_unload_services(hass)
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # Renovação de token do Smart Life altera `data` — não recarrega por isso
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None and coordinator.options_snapshot == dict(entry.options):
        return
    await hass.config_entries.async_reload(entry.entry_id)
