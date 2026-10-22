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

    by_code = {s.code: s for s in specs}
    assert by_code["cur_voltage"].enabled_default is True
    assert by_code["cur_voltage"].entity_category is None
    assert by_code["cur_current"].enabled_default is True
    assert by_code["cur_current"].entity_category is None


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


def test_aliases_v1_v2_luz_thing_model(models):
    """Garante resolução de DPs v1/v2 em lâmpadas mesmo quando Thing Model usa v1."""
    dev = models.MwTuyaDevice(
        device_id="eb9ed27d957425eeccwoin",
        name="BIBLIOTECH",
        category="dj",
        local_key="0123456789abcdef",
        local_ip="192.168.2.63",
    )
    spec = models.DpSpec
    dev.apply_thing_model(
        {
            "switch_led": spec("switch_led", 20, "rw", "bool"),
            "work_mode": spec("work_mode", 21, "rw", "enum", range=["white", "colour"]),
            "bright_value": spec("bright_value", 22, "rw", "value", min=10, max=1000),
            "temp_value": spec("temp_value", 23, "rw", "value", min=0, max=1000),
            "colour_data": spec("colour_data", 24, "rw", "string"),
        }
    )
    # Verifica resolução bidirecional de aliases em dp_map e specs
    assert dev.resolve_dp_id("bright_value") == 22
    assert dev.resolve_dp_id("bright_value_v2") == 22
    assert dev.resolve_dp_id("temp_value") == 23
    assert dev.resolve_dp_id("temp_value_v2") == 23
    assert dev.resolve_dp_id("colour_data") == 24
    assert dev.resolve_dp_id("colour_data_v2") == 24

    assert dev.spec("bright_value_v2") is not None
    assert dev.spec("bright_value_v2").max == 1000
    assert dev.has("bright_value_v2")

    # Local merge sincroniza status em ambos os nomes
    dev.merge_local_dps({"22": 750})
    assert dev.status["bright_value"] == 750
    assert dev.status["bright_value_v2"] == 750


def test_local_key_com_asterisco_eh_valida_mascara_invalida(models):
    # Caso real da lâmpada OESTE e de 20 dispositivos com '*' gerado aleatoriamente pela Tuya
    raw_oeste = {
        "id": "ebe6aae597f0c6ed96iwaq",
        "name": "⬛️💡 OESTE",
        "category": "dj",
        "local_key": "ik*Vy8/7yG^`_O3&",
        "online": True,
    }
    dev_oeste = models.MwTuyaDevice.from_api(raw_oeste, {"ip": "192.168.2.135", "version": "3.3"})
    assert dev_oeste.has_valid_local_key is True
    assert dev_oeste.supports_local is True
    assert dev_oeste.is_local_configured is True

    # Máscaras de API da Tuya (OpenAPI sem permissão de ler local_key)
    raw_masked = {
        "id": "masked_dev",
        "name": "Masked",
        "category": "dj",
        "local_key": "****************",
        "online": True,
    }
    dev_masked = models.MwTuyaDevice.from_api(raw_masked, {"ip": "192.168.2.135", "version": "3.3"})
    assert dev_masked.has_valid_local_key is False
    assert dev_masked.supports_local is False
    assert dev_masked.is_local_configured is False


def test_resolve_dp_fallback_categoria_quando_spec_sem_dp_id(models):
    dev = models.MwTuyaDevice(
        device_id="dj_test",
        name="Lâmpada",
        category="dj",
        local_key="0123456789abcdef",
    )
    spec = models.DpSpec
    # Spec carregada sem dp_id (ex: Smart Life sem local_strategy)
    dev.specs = {
        "switch_led": spec("switch_led", None, "rw", "bool"),
        "bright_value_v2": spec("bright_value_v2", None, "rw", "value"),
    }
    # Deve resolver pelo mapa da categoria 'dj' (1 ou 20 são válidos para switch_led)
    assert dev.resolve_dp_id("switch_led") in (1, 20)
    assert dev.resolve_dp_id("bright_value_v2") == 22
    # Não chuta códigos de outra categoria (ex: plug)
    assert dev.resolve_dp_id("cur_voltage") is None


