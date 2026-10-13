"""Fluxo de configuração em duas etapas da MW Tuya Integration:

1. `async_step_user`: Adiciona e valida uma conta Tuya IoT (permite múltiplas contas
   ativas ao mesmo tempo). Extrai automaticamente todas as `local_key`, categorias e
   cenas, cruzando com a descoberta LAN UDP — **sem criar nenhuma entidade ainda**.
2. `MwTuyaOptionsFlow` (botão **Configurar** na tela da integração):
   - `select_devices`: Selecionar quais dispositivos daquela conta entram no HA.
   - `select_scenes`: Selecionar quais cenas (Tap-to-Run) daquela conta entram no HA.
   - `configure_local`: Definir o modo híbrido (`hybrid_local_first`, `local_only`,
     `cloud_only`) e ajustar os IPs locais dos dispositivos selecionados.
   - `refresh_catalog`: Reconsultar a Tuya Cloud + LAN UDP para atualizar `local_key`
     e novos aparelhos/cenas.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import TuyaApiError, TuyaAuthError, TuyaCloudClient
from .const import (
    CONF_ACCOUNT_NAME,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_LOCAL_HOSTS,
    CONF_LOCAL_VERSIONS,
    CONF_REGION,
    CONF_ROUTING_MODE,
    CONF_SELECTED_DEVICES,
    CONF_SELECTED_SCENES,
    CONF_UID,
    DOMAIN,
    REGIONS,
    ROUTING_HYBRID_LOCAL_FIRST,
    ROUTING_MODES,
)
from .coordinator import MwTuyaCoordinator
from .local import async_discover_lan_devices

_LOGGER = logging.getLogger(__name__)

STEP_ACCOUNT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ACCOUNT_NAME, default="Conta Principal"): str,
        vol.Required(CONF_REGION, default="us"): SelectSelector(
            SelectSelectorConfig(
                options=list(REGIONS),
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="region",
            )
        ),
        vol.Required(CONF_CLIENT_ID): str,
        vol.Required(CONF_CLIENT_SECRET): str,
        vol.Required(CONF_UID): str,
    }
)


class MwTuyaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Fluxo de adição de uma conta Tuya IoT."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            account_name = user_input[CONF_ACCOUNT_NAME].strip()
            region = user_input[CONF_REGION].strip()
            client_id = user_input[CONF_CLIENT_ID].strip()
            client_secret = user_input[CONF_CLIENT_SECRET].strip()
            uid = user_input[CONF_UID].strip()

            # Unique ID composto por região + client_id + uid permite múltiplas contas simultâneas
            unique_id = f"{region}:{client_id}:{uid}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            client = TuyaCloudClient(
                async_get_clientsession(self.hass),
                REGIONS[region],
                client_id,
                client_secret,
                uid,
            )
            try:
                lan_map = await async_discover_lan_devices(timeout=1.5)
                devices = await client.async_list_devices(lan_map)
            except TuyaAuthError:
                errors["base"] = "invalid_auth"
            except TuyaApiError as err:
                _LOGGER.warning("Falha ao validar conta Tuya (%s): %s", account_name, err)
                errors["base"] = "cannot_connect"
            else:
                local_hosts = {
                    d.device_id: d.local_ip for d in devices if d.local_ip and d.has_valid_local_key
                }
                local_versions = {
                    d.device_id: d.local_version
                    for d in devices
                    if d.local_ip and d.has_valid_local_key
                }
                # Cria apenas a conta validada, com 0 devices e 0 cenas selecionados
                # para que o usuário escolha exatamente o que quer em "Configurar".
                return self.async_create_entry(
                    title=f"MW Tuya · {account_name}",
                    data={
                        CONF_ACCOUNT_NAME: account_name,
                        CONF_REGION: region,
                        CONF_CLIENT_ID: client_id,
                        CONF_CLIENT_SECRET: client_secret,
                        CONF_UID: uid,
                        CONF_SELECTED_DEVICES: [],
                        CONF_SELECTED_SCENES: [],
                        CONF_LOCAL_HOSTS: local_hosts,
                        CONF_LOCAL_VERSIONS: local_versions,
                        CONF_ROUTING_MODE: ROUTING_HYBRID_LOCAL_FIRST,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_ACCOUNT_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return MwTuyaOptionsFlow()


class MwTuyaOptionsFlow(OptionsFlow):
    """Gerenciador da conta na tela da integração (Devices, Cenas e Modo Híbrido Local/Cloud)."""

    def _coordinator(self) -> MwTuyaCoordinator | None:
        return self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "select_devices",
                "select_scenes",
                "configure_local",
                "refresh_catalog",
            ],
        )

    async def async_step_select_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Permite escolher quais dispositivos da conta entram no Home Assistant."""
        entry = self.config_entry
        coord = self._coordinator()

        if coord and not coord.catalog_devices:
            await coord.async_load_catalog(scan_lan=False)

        catalog = coord.catalog_devices if coord else {}
        current = list(
            entry.options.get(CONF_SELECTED_DEVICES) or entry.data.get(CONF_SELECTED_DEVICES) or []
        )

        if user_input is not None:
            chosen = list(user_input.get(CONF_SELECTED_DEVICES) or [])
            removed = set(current) - set(chosen)
            if removed:
                dev_reg = dr.async_get(self.hass)
                for did in removed:
                    device_entry = dev_reg.async_get_device(identifiers={(DOMAIN, did)})
                    if device_entry:
                        dev_reg.async_remove_device(device_entry.id)

            new_options = dict(entry.options)
            new_options[CONF_SELECTED_DEVICES] = chosen
            return self.async_create_entry(title="", data=new_options)

        options: list[SelectOptionDict] = []
        for did, dev in sorted(catalog.items(), key=lambda x: x[1].name.lower()):
            mode_tag = (
                f"Local+Cloud ({dev.local_ip})"
                if dev.is_local_configured
                else ("Key pronta (Cloud)" if dev.supports_local else "Cloud")
            )
            label = f"{dev.name} · {dev.category_label} · [{mode_tag}] · {did}"
            options.append(SelectOptionDict(value=did, label=label))

        if not options:
            options = [SelectOptionDict(value=did, label=did) for did in current]

        schema = vol.Schema(
            {
                vol.Optional(CONF_SELECTED_DEVICES, default=current): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="select_devices",
            data_schema=schema,
            description_placeholders={
                "account": entry.data.get(CONF_ACCOUNT_NAME, ""),
                "total": str(len(catalog)),
                "selected": str(len(current)),
            },
        )

    async def async_step_select_scenes(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Permite escolher quais cenas Tap-to-Run da conta entram no Home Assistant."""
        entry = self.config_entry
        coord = self._coordinator()

        if coord and not coord.catalog_scenes:
            await coord.async_load_catalog(scan_lan=False)

        scenes = coord.catalog_scenes if coord else {}
        current = list(
            entry.options.get(CONF_SELECTED_SCENES) or entry.data.get(CONF_SELECTED_SCENES) or []
        )

        if user_input is not None:
            chosen = list(user_input.get(CONF_SELECTED_SCENES) or [])
            new_options = dict(entry.options)
            new_options[CONF_SELECTED_SCENES] = chosen
            return self.async_create_entry(title="", data=new_options)

        options: list[SelectOptionDict] = []
        for sid, scene in sorted(scenes.items(), key=lambda x: x[1].name.lower()):
            home_suffix = f" ({scene.home_name})" if scene.home_name else ""
            options.append(SelectOptionDict(value=sid, label=f"{scene.name}{home_suffix} · {sid}"))

        if not options:
            options = [SelectOptionDict(value=sid, label=sid) for sid in current]

        schema = vol.Schema(
            {
                vol.Optional(CONF_SELECTED_SCENES, default=current): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="select_scenes",
            data_schema=schema,
            description_placeholders={
                "account": entry.data.get(CONF_ACCOUNT_NAME, ""),
                "total": str(len(scenes)),
                "selected": str(len(current)),
            },
        )

    async def async_step_configure_local(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configura política híbrida e IPs locais dos dispositivos selecionados."""
        entry = self.config_entry
        coord = self._coordinator()
        catalog = coord.catalog_devices if coord else {}

        selected = list(
            entry.options.get(CONF_SELECTED_DEVICES) or entry.data.get(CONF_SELECTED_DEVICES) or []
        )
        hosts = dict(entry.options.get(CONF_LOCAL_HOSTS) or entry.data.get(CONF_LOCAL_HOSTS) or {})
        routing = str(
            entry.options.get(CONF_ROUTING_MODE)
            or entry.data.get(CONF_ROUTING_MODE)
            or ROUTING_HYBRID_LOCAL_FIRST
        )

        if user_input is not None:
            new_options = dict(entry.options)
            new_options[CONF_ROUTING_MODE] = user_input.get(
                CONF_ROUTING_MODE, ROUTING_HYBRID_LOCAL_FIRST
            )
            updated_hosts = dict(hosts)
            for did in selected:
                if did in user_input:
                    ip_val = str(user_input.get(did) or "").strip()
                    if ip_val:
                        updated_hosts[did] = ip_val
                    else:
                        updated_hosts.pop(did, None)
            new_options[CONF_LOCAL_HOSTS] = updated_hosts
            return self.async_create_entry(title="", data=new_options)

        fields: dict[Any, Any] = {
            vol.Required(CONF_ROUTING_MODE, default=routing): SelectSelector(
                SelectSelectorConfig(
                    options=ROUTING_MODES,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="routing_mode",
                )
            )
        }
        for did in selected:
            dev = catalog.get(did)
            if dev and not dev.supports_local:
                continue
            suggested = hosts.get(did) or (dev.local_ip if dev else "")
            fields[vol.Optional(did, description={"suggested_value": suggested})] = str

        return self.async_show_form(
            step_id="configure_local",
            data_schema=vol.Schema(fields),
        )

    async def async_step_refresh_catalog(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Atualiza o catálogo da nuvem Tuya (local_keys, devices e cenas) + LAN UDP."""
        coord = self._coordinator()
        if coord is not None:
            await coord.async_load_catalog(scan_lan=True)
            await coord.async_request_refresh()
        return self.async_create_entry(title="", data=dict(self.config_entry.options))
