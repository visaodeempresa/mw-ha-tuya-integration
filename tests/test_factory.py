"""Fábrica guiada pelo Thing Model, escalas e codec de cor (com modelos reais da conta)."""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture(scope="module")
def dpspec(models):
    return importlib.import_module("mwtuya.dpspec")


def _model(props: list[tuple]) -> dict:
    out = []
    for dp, code, access, ts in props:
        out.append({"abilityId": dp, "code": code, "accessMode": access, "typeSpec": ts})
    return {"model": json.dumps({"services": [{"properties": out}]})}


V = "value"
WSDCG = _model(
    [
        (
            1,
            "temp_current",
            "ro",
            {"type": V, "min": -100, "max": 600, "scale": 1, "step": 1, "unit": "℃"},
        ),
        (
            2,
            "humidity_value",
            "ro",
            {"type": V, "min": 0, "max": 1000, "scale": 1, "step": 1, "unit": "%"},
        ),
        (
            4,
            "battery_percentage",
            "ro",
            {"type": V, "min": 0, "max": 100, "scale": 0, "step": 1, "unit": "%"},
        ),
    ]
)
DJ = _model(
    [
        (20, "switch_led", "rw", {"type": "bool"}),
        (21, "work_mode", "rw", {"type": "enum", "range": ["white", "colour", "scene", "music"]}),
        (22, "bright_value_v2", "rw", {"type": V, "min": 10, "max": 1000, "scale": 0, "step": 1}),
        (23, "temp_value_v2", "rw", {"type": V, "min": 0, "max": 1000, "scale": 0, "step": 1}),
        (24, "colour_data_v2", "rw", {"type": "string", "maxlen": 255}),
        (25, "scene_data_v2", "rw", {"type": "string", "maxlen": 255}),
        (
            26,
            "countdown_1",
            "rw",
            {"type": V, "min": 0, "max": 86400, "scale": 0, "step": 1, "unit": "s"},
        ),
    ]
)
KJ = _model(
    [
        (1, "switch", "rw", {"type": "bool"}),
        (3, "mode", "rw", {"type": "enum", "range": ["fresh", "night", "noman"]}),
        (4, "speed", "rw", {"type": "enum", "range": ["1", "2", "3", "4", "5"]}),
        (7, "lock", "rw", {"type": "bool"}),
        (11, "filter_reset", "rw", {"type": "bool"}),
        (
            16,
            "filter_days",
            "ro",
            {"type": V, "min": 0, "max": 90, "scale": 0, "step": 1, "unit": ""},
        ),
    ]
)
MC = _model(
    [
        (
            4,
            "residual_electricity",
            "ro",
            {"type": V, "min": 0, "max": 100, "scale": 0, "step": 1, "unit": "%"},
        ),
        (102, "wd_control", "rw", {"type": "enum", "range": ["open", "close", "pause"]}),
        (104, "wd_percent_control", "rw", {"type": V, "min": 0, "max": 100, "scale": 0, "step": 1}),
        (114, "window_state", "ro", {"type": "enum", "range": ["opened", "closed", "pending"]}),
    ]
)
HPS = _model(
    [
        (1, "presence_state", "ro", {"type": "enum", "range": ["none", "presence"]}),
        (
            4,
            "far_detection",
            "rw",
            {"type": V, "min": 150, "max": 600, "scale": 0, "step": 75, "unit": "cm"},
        ),
    ]
)


def _dev(models, dpspec, category, model, status=None):
    dev = models.MwTuyaDevice(device_id=f"id_{category}", name=category, category=category)
    dev.apply_thing_model(dpspec.parse_thing_model(model))
    dev.status.update(status or {})
    return dev


def _by(models, dev):
    return {s.code: s for s in models.infer_entity_specs(dev)}


def test_wsdcg_umidade_e_temperatura_com_escala_do_modelo(models, dpspec):
    dev = _dev(models, dpspec, "wsdcg", WSDCG, {"temp_current": 253, "humidity_value": 650})
    by = _by(models, dev)
    assert by["humidity_value"].dp.to_ha(650) == 65.0
    assert by["temp_current"].dp.to_ha(253) == 25.3
    assert by["temp_current"].unit == "°C"
    assert by["battery_percentage"].device_class == "battery"
    assert all(s.enabled_default for s in by.values())


def test_luz_v2_agrupa_brilho_temperatura_cor_e_modo(models, dpspec):
    dev = _dev(models, dpspec, "dj", DJ)
    by = _by(models, dev)
    light = by["switch_led"]
    assert light.platform == "light" and light.name is None
    assert light.extra == {
        "switch": "switch_led",
        "bright": "bright_value_v2",
        "temp": "temp_value_v2",
        "colour": "colour_data_v2",
        "mode": "work_mode",
    }
    assert "scene_data_v2" not in by and "work_mode" not in by
    assert by["countdown_1"].platform == "number" and not by["countdown_1"].enabled_default
    assert dev.resolve_dp_id("bright_value_v2") == 22


def test_purificador_vira_fan_com_preset_e_velocidade(models, dpspec):
    by = _by(models, _dev(models, dpspec, "kj", KJ))
    fan = by["switch"]
    assert fan.platform == "fan"
    assert fan.extra["speed"] == "speed" and fan.extra["preset"] == "mode"
    assert by["filter_reset"].platform == "button"
    assert by["lock"].platform == "switch" and by["lock"].entity_category == "config"


def test_janela_mc_usa_wd_control_e_estado(models, dpspec):
    by = _by(models, _dev(models, dpspec, "mc", MC))
    cover = by["wd_control"]
    assert cover.platform == "cover" and cover.device_class == "window"
    assert cover.extra["position"] == "wd_percent_control"
    assert cover.extra["window_state"] == "window_state"
    assert by["residual_electricity"].device_class == "battery"


def test_presenca_enum_vira_binary_sensor_e_numero_com_passo(models, dpspec):
    by = _by(models, _dev(models, dpspec, "hps", HPS))
    assert by["presence_state"].platform == "binary_sensor"
    assert by["presence_state"].options == ["presence"]
    far = by["far_detection"]
    assert far.platform == "number" and far.step == 75 and far.min_value == 150
    assert far.dp.from_ha(400) == 375


def test_categoria_ir_nao_gera_entidades(models):
    dev = models.MwTuyaDevice(
        device_id="x", name="IR", category="wnykq", status={"control": "send_ir"}
    )
    assert models.infer_entity_specs(dev) == []


def test_codec_cor_v2_local_hex_ida_e_volta(dpspec):
    assert dpspec.decode_local("colour_data_v2", "00f003e801f4") == '{"h":240,"s":1000,"v":500}'
    assert dpspec.encode_local("colour_data_v2", '{"h":240,"s":1000,"v":500}') == "00f003e801f4"


def test_codec_cor_v1_hex_de_14(dpspec):
    hsv = dpspec.parse_hsv("ff00000000ffff")
    assert hsv == {"h": 0, "s": 255, "v": 255}
    assert dpspec.encode_local("colour_data", '{"h":0,"s":255,"v":255}', 14) == "ff00000000ffff"


def test_merge_local_decodifica_cor_e_lembra_formato(models, dpspec):
    dev = _dev(models, dpspec, "dj", DJ)
    dev.merge_local_dps({"24": "000003e803e8", "20": True})
    assert dev.status["colour_data_v2"] == '{"h":0,"s":1000,"v":1000}'
    assert dev.local_hex_len["colour_data_v2"] == 12
    assert dev.status["switch_led"] is True


def test_resolve_dp_nunca_chuta_quando_ha_modelo(models, dpspec):
    dev = _dev(models, dpspec, "dj", DJ)
    assert dev.resolve_dp_id("cur_voltage") is None


SP = _model(
    [
        (101, "basic_indicator", "rw", {"type": "bool"}),
        (105, "basic_private", "rw", {"type": "bool"}),
        (134, "motion_switch", "rw", {"type": "bool"}),
        (150, "record_switch", "rw", {"type": "bool"}),
        (159, "siren_switch", "rw", {"type": "bool"}),
        (162, "device_restart", "rw", {"type": "bool"}),
        (119, "ptz_control", "rw", {"type": "enum", "range": ["0", "1", "2"]}),
    ]
)
SD = _model(
    [
        (1, "power_go", "rw", {"type": "bool"}),
        (3, "mode", "rw", {"type": "enum", "range": ["standby", "smart", "chargego"]}),
        (5, "status", "ro", {"type": "enum", "range": ["standby", "smart_clean", "charging"]}),
        (13, "seek", "rw", {"type": "bool"}),
        (6, "electricity_left", "ro", {"type": V, "min": 0, "max": 100, "scale": 0, "step": 1}),
    ]
)
WXKG = _model(
    [
        (1, "switch_mode1", "ro", {"type": "enum", "range": ["click", "double_click", "press"]}),
        (10, "battery_percentage", "ro", {"type": V, "min": 0, "max": 100, "scale": 0, "step": 1}),
    ]
)


def test_camera_sp_gera_camera_led_sirene_e_reinicio(models, dpspec):
    specs = models.infer_entity_specs(_dev(models, dpspec, "sp", SP, {"alarm_message": ""}))
    plat = {(s.platform, s.code) for s in specs}
    cam = next(s for s in specs if s.platform == "camera")
    assert cam.extra == {
        "private": "basic_private",
        "record": "record_switch",
        "motion": "motion_switch",
    }
    assert ("light", "basic_indicator") in plat
    assert ("siren", "siren_switch") in plat
    assert ("button", "device_restart") in plat
    assert ("event", "alarm_message") in plat
    assert not any(s.code == "ptz_control" for s in specs)


def test_aspirador_sd_vira_vacuum(models, dpspec):
    specs = models.infer_entity_specs(_dev(models, dpspec, "sd", SD))
    vac = next(s for s in specs if s.platform == "vacuum")
    assert vac.code == "power_go"
    assert vac.extra["mode"] == "mode" and vac.extra["seek"] == "seek"
    assert not any(s.platform == "button" and s.code == "seek" for s in specs)


def test_botao_sem_fio_vira_event_com_tipos_do_modelo(models, dpspec):
    specs = models.infer_entity_specs(_dev(models, dpspec, "wxkg", WXKG))
    ev = next(s for s in specs if s.platform == "event")
    assert ev.code == "switch_mode1"
    assert ev.options == ["click", "double_click", "press"]
