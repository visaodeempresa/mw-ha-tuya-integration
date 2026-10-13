"""Testes unitários dos modelos híbridos (Local + Cloud) e inferência de entidades."""

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


def test_hub_ir_eh_cloud_only(models):
    dev = models.MwTuyaDevice(
        device_id="ir1",
        name="Hub IR Sala",
        category="wnykq",
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
