"""Migração das integrações `tuya` (nativa) e `localtuya` para a MW Tuya.

Para cada entidade legada que corresponde a uma entidade MW (mesmo aparelho,
mesmo domínio e mesmo DP), a entidade MW herda **o `entity_id`**, nome, ícone,
aliases, área, labels, estado habilitado/oculto e as opções de exposição a
assistentes (Assist/Letícia, Alexa, Google). A legada é renomeada para
`<entity_id>_legacy` e desabilitada — nada é apagado, tudo é reversível.

Automações, scripts, dashboards e a Letícia continuam funcionando porque o
`entity_id` é preservado.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_SELECTED_DEVICES, CONF_SELECTED_SCENES, DOMAIN

LEGACY_PLATFORMS = ("tuya", "localtuya")
PRIMARY_DOMAINS = {"light", "fan", "cover", "humidifier", "climate", "vacuum", "camera"}
LEGACY_SUFFIX = "_legacy"


@dataclass(slots=True)
class LegacyRef:
    """Entidade legada já resolvida para (aparelho, domínio, código)."""

    entity_id: str
    platform: str
    device_id: str
    domain: str
    code: str
    enabled: bool
    exposed: bool
    is_scene: bool = False

    @property
    def score(self) -> tuple[bool, bool, bool]:
        return (self.enabled, self.exposed, self.platform == "tuya")


@dataclass(slots=True)
class MigrationPlan:
    pairs: list[tuple[LegacyRef, str]] = field(default_factory=list)
    shadowed: list[LegacyRef] = field(default_factory=list)
    unmatched: list[LegacyRef] = field(default_factory=list)
    devices_to_select: dict[str, set[str]] = field(default_factory=dict)
    scenes_to_select: dict[str, set[str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "migrar": [
                {"de": ref.entity_id, "mw": mw, "plataforma": ref.platform}
                for ref, mw in self.pairs
            ],
            "duplicadas_legadas": [r.entity_id for r in self.shadowed],
            "sem_correspondente": [r.entity_id for r in self.unmatched if r.enabled or r.exposed],
            "dispositivos_a_selecionar": {k: sorted(v) for k, v in self.devices_to_select.items()},
            "cenas_a_selecionar": {k: sorted(v) for k, v in self.scenes_to_select.items()},
        }


def _exposed(entry: er.RegistryEntry) -> bool:
    return bool((entry.options or {}).get("conversation", {}).get("should_expose"))


def _legacy_device_id(dev_reg: dr.DeviceRegistry, entry: er.RegistryEntry) -> str:
    if not entry.device_id:
        return ""
    device = dev_reg.async_get(entry.device_id)
    if not device:
        return ""
    for domain, ident in device.identifiers:
        if domain in LEGACY_PLATFORMS:
            return str(ident).removeprefix("local_")
    return ""


def resolve_legacy(
    entry: er.RegistryEntry, tuya_device_id: str, dp_to_code: dict[str, dict[int, str]]
) -> LegacyRef | None:
    """Traduz o unique_id legado em (aparelho, domínio, código)."""
    uid = str(entry.unique_id or "")
    domain = entry.entity_id.split(".", 1)[0]
    enabled = entry.disabled_by is None
    exposed = _exposed(entry)
    if entry.platform == "tuya":
        if domain == "scene" and uid.startswith("tys"):
            return LegacyRef(entry.entity_id, "tuya", "", domain, uid[3:], enabled, exposed, True)
        rest = uid.removeprefix("tuya.")
        did = tuya_device_id or rest[:22]
        code = rest[len(did) :] if rest.startswith(did) else ""
        return LegacyRef(entry.entity_id, "tuya", did, domain, code, enabled, exposed)
    if entry.platform == "localtuya" and uid.startswith("local_"):
        did, _, dp = uid.removeprefix("local_").rpartition("_")
        code = dp_to_code.get(did, {}).get(int(dp)) if dp.isdigit() else None
        return LegacyRef(entry.entity_id, "localtuya", did, domain, code or "", enabled, exposed)
    return None


def build_plan(hass: HomeAssistant, coordinators: list[Any]) -> MigrationPlan:
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    plan = MigrationPlan()

    owner: dict[str, Any] = {}
    dp_to_code: dict[str, dict[int, str]] = {}
    scene_owner: dict[str, Any] = {}
    for coord in coordinators:
        for did, dev in coord.catalog_devices.items():
            owner[did] = coord
            dp_to_code[did] = {v: k for k, v in dev.dp_map.items()}
        for sid in coord.catalog_scenes:
            scene_owner[sid] = coord

    # Índice das entidades MW: (device, domínio, código) e cenas por scene_id
    mw_by_key: dict[tuple[str, str, str], str] = {}
    mw_primary: dict[tuple[str, str], list[str]] = {}
    mw_scene: dict[str, str] = {}
    for ent in ent_reg.entities.values():
        if ent.platform != DOMAIN:
            continue
        parts = str(ent.unique_id).split("_", 2)
        if len(parts) == 3:
            did, plat, code = parts
            if plat == "scene":
                mw_scene[code] = ent.entity_id
                continue
            mw_by_key[(did, plat, code)] = ent.entity_id
            if plat in PRIMARY_DOMAINS:
                mw_primary.setdefault((did, plat), []).append(ent.entity_id)

    best: dict[str, LegacyRef] = {}
    for ent in list(ent_reg.entities.values()):
        if ent.platform not in LEGACY_PLATFORMS or ent.entity_id.endswith(LEGACY_SUFFIX):
            continue
        ref = resolve_legacy(ent, _legacy_device_id(dev_reg, ent), dp_to_code)
        if ref is None:
            continue
        if ref.is_scene:
            target = mw_scene.get(ref.code)
            if not target and ref.code in scene_owner and (ref.enabled or ref.exposed):
                entry_id = scene_owner[ref.code].config_entry.entry_id
                plan.scenes_to_select.setdefault(entry_id, set()).add(ref.code)
        else:
            if ref.device_id not in owner:
                plan.unmatched.append(ref)
                continue
            target = mw_by_key.get((ref.device_id, ref.domain, ref.code))
            if not target and ref.domain in PRIMARY_DOMAINS:
                cands = mw_primary.get((ref.device_id, ref.domain), [])
                target = cands[0] if len(cands) == 1 else None
            if not target and (ref.enabled or ref.exposed):
                selected = set(owner[ref.device_id].selected_device_ids)
                if ref.device_id not in selected:
                    entry_id = owner[ref.device_id].config_entry.entry_id
                    plan.devices_to_select.setdefault(entry_id, set()).add(ref.device_id)
        if not target:
            plan.unmatched.append(ref)
            continue
        cur = best.get(target)
        if cur is None or ref.score > cur.score:
            if cur is not None:
                plan.shadowed.append(cur)
            best[target] = ref
        else:
            plan.shadowed.append(ref)

    plan.pairs = sorted(((ref, mw) for mw, ref in best.items()), key=lambda p: p[0].entity_id)
    return plan


def _free_entity_id(ent_reg: er.EntityRegistry, wanted: str) -> str:
    candidate, n = wanted, 2
    while ent_reg.async_get(candidate) is not None:
        candidate = f"{wanted}_{n}"
        n += 1
    return candidate


def _friendly(hass: HomeAssistant, entity_id: str) -> str | None:
    state = hass.states.get(entity_id)
    name = state.attributes.get("friendly_name") if state else None
    return str(name) if name else None


def apply_plan(hass: HomeAssistant, plan: MigrationPlan) -> dict[str, Any]:
    """Executa o plano: MW herda entity_id/metadados; legada vira `_legacy` desabilitada."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    done: list[str] = []
    errors: dict[str, str] = {}
    moved_devices: set[str] = set()

    for ref, mw_eid in plan.pairs:
        old = ent_reg.async_get(ref.entity_id)
        new = ent_reg.async_get(mw_eid)
        if old is None or new is None:
            errors[ref.entity_id] = "entidade sumiu do registro"
            continue
        try:
            fname = old.name or _friendly(hass, old.entity_id)
            legacy_eid = _free_entity_id(ent_reg, f"{old.entity_id}{LEGACY_SUFFIX}")
            ent_reg.async_update_entity(
                old.entity_id,
                new_entity_id=legacy_eid,
                disabled_by=er.RegistryEntryDisabler.USER,
            )
            ent_reg.async_update_entity(
                new.entity_id,
                new_entity_id=old.entity_id,
                name=fname,
                icon=old.icon,
                aliases=copy.copy(old.aliases),
                area_id=old.area_id,
                labels=set(old.labels),
                disabled_by=None if old.disabled_by is None else er.RegistryEntryDisabler.USER,
                hidden_by=old.hidden_by,
            )
            for opt_domain, opts in (old.options or {}).items():
                if opt_domain in LEGACY_PLATFORMS:
                    continue
                ent_reg.async_update_entity_options(old.entity_id, opt_domain, dict(opts))
            if old.device_id and new.device_id and new.device_id not in moved_devices:
                legacy_dev = dev_reg.async_get(old.device_id)
                mw_dev = dev_reg.async_get(new.device_id)
                if legacy_dev and mw_dev:
                    dev_reg.async_update_device(
                        mw_dev.id,
                        name_by_user=mw_dev.name_by_user or legacy_dev.name_by_user,
                        area_id=mw_dev.area_id or legacy_dev.area_id,
                    )
                    moved_devices.add(new.device_id)
            done.append(old.entity_id)
        except Exception as err:
            errors[ref.entity_id] = str(err)
    return {"migradas": done, "erros": errors}


async def async_select_missing(hass: HomeAssistant, plan: MigrationPlan) -> dict[str, int]:
    """Adiciona à seleção da MW os aparelhos/cenas que a integração legada usa."""
    changed: dict[str, int] = {}
    for entry_id in set(plan.devices_to_select) | set(plan.scenes_to_select):
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            continue
        opts = dict(entry.options)
        devs = set(opts.get(CONF_SELECTED_DEVICES) or entry.data.get(CONF_SELECTED_DEVICES) or [])
        scenes = set(opts.get(CONF_SELECTED_SCENES) or entry.data.get(CONF_SELECTED_SCENES) or [])
        add_d = plan.devices_to_select.get(entry_id, set()) - devs
        add_s = plan.scenes_to_select.get(entry_id, set()) - scenes
        if not add_d and not add_s:
            continue
        opts[CONF_SELECTED_DEVICES] = sorted(devs | add_d)
        opts[CONF_SELECTED_SCENES] = sorted(scenes | add_s)
        hass.config_entries.async_update_entry(entry, options=opts)
        changed[entry.title] = len(add_d) + len(add_s)
    return changed
