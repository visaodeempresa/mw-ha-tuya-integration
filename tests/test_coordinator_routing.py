"""Roteador híbrido: erro de nuvem chega como erro de serviço e persiste entre reinícios.

Cenário real — luzes do escritório: sem rota local válida e com o canal Smart Life
fora do ar, o comando ia cru para a OpenAPI e estourava `TuyaApiError [60001001]`
sob a forma de 500 no /api/services. Deve virar um erro tratável de serviço e o
cache do canal Smart Life precisa sobreviver ao restart do Home Assistant.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def cw(models):
    if "mwtuya" not in sys.modules:
        pkg = ModuleType("mwtuya")
        pkg.__path__ = [str(RAIZ / "custom_components" / "mw_tuya")]
        sys.modules["mwtuya"] = pkg
    return importlib.import_module("mwtuya.coordinator")


@pytest.fixture()
def dev(models):
    return models.MwTuyaDevice(
        device_id="ebf3214e780d8936935b7j",
        name="⬛️💡 LESTE",
        category="dj",
        dp_map={"switch_led": 20},
        online=True,
    )


def _coordinator(cw, dev, client=None):
    c = cw.MwTuyaCoordinator.__new__(cw.MwTuyaCoordinator)
    c.client = client
    c.smartlife = None
    c.account_name = "Conta Teste"
    c.config_entry = SimpleNamespace(
        data={
            "routing_mode": "hybrid_local_first",
            "selected_devices": [dev.device_id],
        },
        options={},
    )
    c.catalog_devices = {dev.device_id: dev}
    c.local_clients = {}
    c.local_ok = {}
    c._local_misses = {}
    c.stats = {}
    c.hass = None
    return c


def test_erro_quota_vira_erro_de_servico(cw, models, dev):
    from homeassistant.exceptions import HomeAssistantError

    api = importlib.import_module("mwtuya.api")

    class ClientEsgotado:
        async def async_send_commands(self, did, payload):
            raise api.TuyaApiError("60001001", "Your controllable device pool quota is insufficient", "/commands")

    c = _coordinator(cw, dev, client=ClientEsgotado())
    with pytest.raises(HomeAssistantError) as exc:
        asyncio.run(c.async_send_device_commands(dev.device_id, {"switch_led": True}))
    assert "60001001" in str(exc.value)
    # o estado do aparelho NÃO deve ser atualizado quando o comando falha
    assert dev.status.get("switch_led") is not True


def test_erro_quota_faz_fallback_automatico_para_local(cw, models, dev):
    api = importlib.import_module("mwtuya.api")

    class ClientEsgotado:
        async def async_send_commands(self, did, payload):
            raise api.TuyaApiError("60001001", "Your controllable device pool quota is insufficient", "/commands")

    class FakeLocalClient:
        def __init__(self):
            self.sent_dps = None

        async def async_set_dps(self, dps, node_id=""):
            self.sent_dps = dps
            return True

    fake_local = FakeLocalClient()
    c = _coordinator(cw, dev, client=ClientEsgotado())
    c.local_clients[dev.device_id] = fake_local
    c.local_ok[dev.device_id] = False  # Simula poller offline temporário

    route = asyncio.run(c.async_send_device_commands(dev.device_id, {"switch_led": True}))
    assert route in ("local", "local_fallback")
    assert fake_local.sent_dps == {"20": True}
    assert dev.status.get("switch_led") is True
    assert c.local_ok[dev.device_id] is True


def test_restauro_do_cache_do_canal_smartlife_cruza_restart(cw):
    c = cw.MwTuyaCoordinator.__new__(cw.MwTuyaCoordinator)
    c.sl_devices = set()
    c.sl_scenes = set()
    c._restore_sl_cache(
        {"sl_devices": ["ebf3214e780d8936935b7j", ""], "sl_scenes": ["scene-1"]}
    )
    assert c.sl_devices == {"ebf3214e780d8936935b7j"}
    assert c.sl_scenes == {"scene-1"}
    # cache inválido não suja nenhum conjunto
    c._restore_sl_cache({"sl_devices": 42, "sl_scenes": None})
    assert c.sl_devices == {"ebf3214e780d8936935b7j"}
    c._restore_sl_cache({})
    assert c.sl_scenes == {"scene-1"}
