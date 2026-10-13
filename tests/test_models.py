"""Testes unitários dos modelos híbridos (Local + Cloud), Shadow v2.0 e inferência de entidades."""

from __future__ import annotations


def test_dispositivo_com_local_key_e_ip_eh_hibrido(models):
    raw = {
        "id": "eb77229b2a9fafa74ee2pc",
        "name": "Cafeteira",
        "category": "cz",
        "product_name": "Smart Plug",
        "online": True,
        "local_key": "0123456789abcdef",
        "status": [
            {"code": "switch_1", "value": True},
            {"code": "cur_power", "value": 1250},
            {"code": "cur_voltage", "value": 2205},
            {"code": "cur_current", "value": 560},
        ],
    }
    dev = models.MwTuyaDevice.from_api(raw, {"ip": "192.168.1.120", "version": "3.3"})
    assert dev.has_valid_local_key
    assert dev.supports_local
    assert dev.is_local_configured
    assert dev.resolve_dp_id("switch_1") == 1
    assert dev.resolve_dp_id("cur_power") == 19

    specs = models.infer_entity_specs(dev)
    plataformas = {(s.platform, s.code) for s in specs}
    assert ("switch", "switch_1") in plataformas
    assert ("sensor", "cur_power") in plataformas
    assert ("sensor", "cur_voltage") in plataformas
    assert ("sensor", "cur_current") in plataformas


def test_thing_model_mapeia_dp_id_e_infere_select_number_button(models):
    dev = models.MwTuyaDevice(
        device_id="ebcc203220f73515cfgmza",
        name="Régua da Mesa",
        category="pc",
        local_key="0123456789abcdef",
    )
    spec = models.DpSpec
    dev.apply_thing_model(
        {
            "switch_1": spec("switch_1", 1, "rw", "bool"),
            "countdown_1": spec("countdown_1", 9, "rw", "value", 0, 86400, 0, 1, "s"),
            "relay_status": spec("relay_status", 38, "rw", "enum", range=["off", "on", "memory"]),
            "child_lock": spec("child_lock", 41, "rw", "bool"),
            "reset_add_ele": spec("reset_add_ele", 201, "rw", "bool"),
        }
    )
    dev.apply_shadow_properties(
        [
            {"code": "switch_1", "dp_id": 1, "value": True, "custom_name": "Monitor"},
            {"code": "countdown_1", "dp_id": 9, "value": 120},
            {"code": "relay_status", "dp_id": 38, "value": "memory"},
            {"code": "child_lock", "dp_id": 41, "value": False},
            {"code": "reset_add_ele", "dp_id": 201, "value": False},
        ]
    )
    assert dev.resolve_dp_id("relay_status") == 38
    assert dev.resolve_dp_id("reset_add_ele") == 201
    assert dev.custom_names["switch_1"] == "Monitor"

    specs = models.infer_entity_specs(dev)
    by_code = {s.code: s for s in specs}
    assert by_code["switch_1"].name == "Monitor"
    assert by_code["relay_status"].platform == "select"
    assert by_code["relay_status"].dp_id == 38
    assert by_code["countdown_1"].platform == "number"
    assert by_code["countdown_1"].dp_id == 9
    assert by_code["reset_add_ele"].platform == "button"
    assert by_code["reset_add_ele"].dp_id == 201


def test_merge_local_dps_atualiza_status_semantico(models):
    dev = models.MwTuyaDevice(
        device_id="dev1",
        name="Régua Escritório",
        category="pc",
        local_key="0123456789abcdef",
        status={"switch_1": False, "switch_2": False, "cur_power": 0},
    )
    dev.merge_local_dps({"1": True, "2": False, "19": 450})
    assert dev.status["switch_1"] is True
    assert dev.status["cur_power"] == 450


def test_controle_virtual_ir_eh_cloud_only(models):
    dev = models.MwTuyaDevice(
        device_id="ir_ac_1",
        name="Ar Condicionado IR",
        category="infrared_ac",
        local_key="0123456789abcdef",
    )
    assert not dev.supports_local


def test_cena_serializacao(models):
    sc = models.MwTuyaScene(
        scene_id="tys123",
        name="Cinema",
        home_id="h1",
        home_name="Casa Principal",
    )
    copia = models.MwTuyaScene.from_dict(sc.to_dict())
    assert copia.scene_id == "tys123"
    assert copia.name == "Cinema"
    assert copia.home_name == "Casa Principal"


def test_sem_thing_model_nao_cria_controle_por_palpite(models):
    dev = models.MwTuyaDevice(
        device_id="dev2",
        name="Sem modelo",
        category="pc",
        status={"switch_1": True, "relay_status": "memory", "countdown_1": 0},
    )
    by_code = {s.code: s for s in models.infer_entity_specs(dev)}
    assert by_code["switch_1"].platform == "switch"
    assert by_code["relay_status"].platform == "sensor"
    assert by_code["countdown_1"].platform == "sensor"
