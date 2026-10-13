"""Serviços da MW Tuya Integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from .const import DOMAIN
from .coordinator import HomeAssistantError, MwTuyaCoordinator

SERVICE_REFRESH_CATALOG = "refresh_catalog"
SERVICE_SCAN_LAN = "scan_lan"
SERVICE_SEND_COMMAND = "send_command"
SERVICE_TRIGGER_SCENE = "trigger_scene"

SCHEMA_SEND_COMMAND = vol.Schema(
    {
        vol.Required("device_id"): str,
        vol.Required("code"): str,
        vol.Required("value"): vol.Any(bool, int, float, str, dict, list),
        vol.Optional("dp_id"): int,
    }
)

SCHEMA_TRIGGER_SCENE = vol.Schema(
    {
        vol.Required("scene_id"): str,
    }
)


def _iter_coordinators(hass: HomeAssistant) -> list[MwTuyaCoordinator]:
    return [c for c in hass.data.get(DOMAIN, {}).values() if isinstance(c, MwTuyaCoordinator)]


def async_setup_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH_CATALOG):
        return

    async def handle_refresh_catalog(call: ServiceCall) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for coord in _iter_coordinators(hass):
            await coord.async_load_catalog(scan_lan=True)
            await coord.async_request_refresh()
            summary[coord.account_name] = {
                "devices_total": len(coord.catalog_devices),
                "devices_selected": len(coord.active_devices),
                "scenes_total": len(coord.catalog_scenes),
                "scenes_selected": len(coord.active_scenes),
                "lan_discovered": len(coord.lan_map),
            }
        return summary

    async def handle_scan_lan(call: ServiceCall) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for coord in _iter_coordinators(hass):
            await coord.async_load_catalog(scan_lan=True)
            summary[coord.account_name] = coord.lan_map
        return summary

    async def handle_send_command(call: ServiceCall) -> dict[str, Any]:
        device_id = str(call.data["device_id"]).strip()
        code = str(call.data["code"]).strip()
        value = call.data["value"]
        dp_id = call.data.get("dp_id")

        for coord in _iter_coordinators(hass):
            if device_id in coord.catalog_devices:
                route = await coord.async_send_device_command(device_id, code, value, dp_id=dp_id)
                return {
                    "ok": True,
                    "account": coord.account_name,
                    "device_id": device_id,
                    "route": route,
                }
        raise HomeAssistantError(
            f"Dispositivo {device_id} não encontrado em nenhuma conta configurada."
        )

    async def handle_trigger_scene(call: ServiceCall) -> dict[str, Any]:
        scene_id = str(call.data["scene_id"]).strip()
        for coord in _iter_coordinators(hass):
            if scene_id in coord.catalog_scenes:
                ok = await coord.async_trigger_scene(scene_id)
                return {
                    "ok": ok,
                    "account": coord.account_name,
                    "scene_id": scene_id,
                }
        raise HomeAssistantError(f"Cena {scene_id} não encontrada em nenhuma conta configurada.")

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_CATALOG,
        handle_refresh_catalog,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN_LAN,
        handle_scan_lan,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_COMMAND,
        handle_send_command,
        schema=SCHEMA_SEND_COMMAND,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_TRIGGER_SCENE,
        handle_trigger_scene,
        schema=SCHEMA_TRIGGER_SCENE,
        supports_response=SupportsResponse.OPTIONAL,
    )


def async_unload_services(hass: HomeAssistant) -> None:
    for svc in (
        SERVICE_REFRESH_CATALOG,
        SERVICE_SCAN_LAN,
        SERVICE_SEND_COMMAND,
        SERVICE_TRIGGER_SCENE,
    ):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)
