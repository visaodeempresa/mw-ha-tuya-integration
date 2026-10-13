"""MW Tuya Integration — controle híbrido Local & Cloud multi-conta no Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TuyaApiError, TuyaAuthError, TuyaCloudClient
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_REGION,
    CONF_UID,
    DOMAIN,
    REGIONS,
)
from .coordinator import MwTuyaCoordinator
from .services import async_setup_services, async_unload_services

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
    client = TuyaCloudClient(
        session,
        base_url,
        data[CONF_CLIENT_ID],
        data[CONF_CLIENT_SECRET],
        data[CONF_UID],
    )

    coordinator = MwTuyaCoordinator(hass, entry, client)
    try:
        await coordinator.async_load_catalog(scan_lan=True)
    except TuyaAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except TuyaApiError as err:
        raise ConfigEntryNotReady(f"Tuya Cloud indisponível: {err}") from err

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(
        coordinator.async_start_push(
            session, base_url, data[CONF_CLIENT_ID], data[CONF_CLIENT_SECRET]
        )
    )
    async_setup_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN, None)
            async_unload_services(hass)
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
