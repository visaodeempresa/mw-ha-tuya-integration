"""Migração tuya/localtuya → MW: resolução de unique_id e escolha do vencedor."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
mig = importlib.import_module("custom_components.mw_tuya.migration")


def _ent(entity_id, platform, unique_id, device_id=None, disabled=False, exposed=False):
    return SimpleNamespace(
        entity_id=entity_id,
        platform=platform,
        unique_id=unique_id,
        device_id=device_id,
        disabled_by="user" if disabled else None,
        options={"conversation": {"should_expose": exposed}} if exposed else {},
    )


def test_resolve_tuya_nativa_com_codigo():
    ref = mig.resolve_legacy(
        _ent("light.sala", "tuya", "tuya.ebe6aae597f0c6ed96iwaqswitch_led"),
        "ebe6aae597f0c6ed96iwaq",
        {},
    )
    assert (ref.device_id, ref.domain, ref.code) == (
        "ebe6aae597f0c6ed96iwaq",
        "light",
        "switch_led",
    )


def test_resolve_tuya_nativa_sem_codigo_fan():
    ref = mig.resolve_legacy(
        _ent("fan.purificador", "tuya", "tuya.70546171ecfabc7c72a6"), "70546171ecfabc7c72a6", {}
    )
    assert ref.code == "" and ref.domain == "fan"


def test_resolve_cena_nativa():
    ref = mig.resolve_legacy(_ent("scene.amarelao", "tuya", "tysg3TtdFwxAf4oqDAP"), "", {})
    assert ref.is_scene and ref.code == "g3TtdFwxAf4oqDAP"


def test_resolve_localtuya_traduz_dp_pelo_modelo():
    ref = mig.resolve_legacy(
        _ent("light.mesa_local", "localtuya", "local_ebed2f8cc4cdd921bdcjm1_20"),
        "",
        {"ebed2f8cc4cdd921bdcjm1": {20: "switch_led"}},
    )
    assert (ref.device_id, ref.code, ref.platform) == (
        "ebed2f8cc4cdd921bdcjm1",
        "switch_led",
        "localtuya",
    )


def _plan(monkeypatch, entities, devices, coord):
    ent_reg = SimpleNamespace(entities={e.entity_id: e for e in entities})
    dev_reg = SimpleNamespace(async_get=lambda did: devices.get(did))
    monkeypatch.setattr(mig.er, "async_get", lambda hass: ent_reg)
    monkeypatch.setattr(mig.dr, "async_get", lambda hass: dev_reg)
    return mig.build_plan(None, [coord])


def test_plano_prefere_legada_habilitada_e_exposta(monkeypatch):
    did = "ebe6aae597f0c6ed96iwaq"
    coord = SimpleNamespace(
        catalog_devices={did: SimpleNamespace(dp_map={"switch_led": 20})},
        catalog_scenes={},
        selected_device_ids=[did],
        config_entry=SimpleNamespace(entry_id="E1"),
    )
    devices = {
        "d_tuya": SimpleNamespace(identifiers={("tuya", did)}),
        "d_lt": SimpleNamespace(identifiers={("localtuya", f"local_{did}")}),
    }
    ents = [
        _ent("light.mw_nova", "mw_tuya", f"{did}_light_switch_led"),
        _ent("light.sala", "tuya", f"tuya.{did}switch_led", "d_tuya", disabled=True, exposed=True),
        _ent(
            "light.sala_local", "localtuya", f"local_{did}_20", "d_lt", disabled=False, exposed=True
        ),
    ]
    plan = _plan(monkeypatch, ents, devices, coord)
    assert [(r.entity_id, mw) for r, mw in plan.pairs] == [("light.sala_local", "light.mw_nova")]
    assert [r.entity_id for r in plan.shadowed] == ["light.sala"]


def test_plano_lista_aparelho_nao_selecionado_em_uso(monkeypatch):
    did = "eb40e25c043fa6e250lu8f"
    coord = SimpleNamespace(
        catalog_devices={did: SimpleNamespace(dp_map={})},
        catalog_scenes={"g3TtdFwxAf4oqDAP": object()},
        selected_device_ids=[],
        config_entry=SimpleNamespace(entry_id="E1"),
    )
    devices = {"d": SimpleNamespace(identifiers={("tuya", did)})}
    ents = [
        _ent("switch.corredor", "tuya", f"tuya.{did}switch_1", "d", exposed=True),
        _ent("scene.amarelao", "tuya", "tysg3TtdFwxAf4oqDAP", exposed=True),
    ]
    plan = _plan(monkeypatch, ents, devices, coord)
    assert plan.devices_to_select == {"E1": {did}}
    assert plan.scenes_to_select == {"E1": {"g3TtdFwxAf4oqDAP"}}
    assert plan.pairs == []
