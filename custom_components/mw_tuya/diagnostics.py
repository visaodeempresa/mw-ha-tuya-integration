"""Diagnóstico da MW Tuya Integration — oculta `client_secret` e `local_key`."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_CLIENT_SECRET, DOMAIN
from .coordinator import MwTuyaCoordinator

TO_REDACT = {
    CONF_CLIENT_SECRET,
    "local_key",
    "access_token",
    "refresh_token",
    "user_code",
    "terminal_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: MwTuyaCoordinator = hass.data[DOMAIN][entry.entry_id]
    devices_summary = {
        did: {
            "name": dev.name,
            "category": dev.category,
            "online": dev.online,
            "local_ip": dev.local_ip,
            "local_version": dev.local_version,
            "has_valid_local_key": dev.has_valid_local_key,
            "selected": did in coordinator.selected_device_ids,
            "status": dev.status,
        }
        for did, dev in coordinator.catalog_devices.items()
    }
    scenes_summary = {
        sid: {
            "name": sc.name,
            "home_name": sc.home_name,
            "selected": sid in coordinator.selected_scene_ids,
        }
        for sid, sc in coordinator.catalog_scenes.items()
    }
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "account_name": coordinator.account_name,
        "routing_mode": coordinator.routing_mode,
        "stats": coordinator.stats,
        "lan_discovered": coordinator.lan_map,
        "catalog_devices_count": len(coordinator.catalog_devices),
        "selected_devices_count": len(coordinator.active_devices),
        "catalog_scenes_count": len(coordinator.catalog_scenes),
        "selected_scenes_count": len(coordinator.active_scenes),
        "devices": devices_summary,
        "scenes": scenes_summary,
    }
