"""Canal Smart Life: specs a partir de function/status_range e dp_id da estratégia local."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

pytest.importorskip("tuya_sharing")


@pytest.fixture(scope="module")
def sl(models):
    return importlib.import_module("mwtuya.smartlife")


def _dev():
    fn = SimpleNamespace
    return SimpleNamespace(
        id="dev1",
        name="Luz",
        category="dj",
        product_id="p1",
        product_name="Bulb",
        online=True,
        local_key="0123456789abcdef",
        sub=False,
        status={"switch_led": True, "temp_current": 253},
        function={
            "switch_led": fn(code="switch_led", type="Boolean", values="{}"),
            "work_mode": fn(code="work_mode", type="Enum", values='{"range":["white","colour"]}'),
        },
        status_range={
            "switch_led": fn(code="switch_led", type="Boolean", values="{}"),
            "temp_current": fn(
                code="temp_current",
                type="Integer",
                values='{"unit":"℃","min":-200,"max":600,"scale":1,"step":1}',
            ),
        },
        local_strategy={20: {"status_code": "switch_led"}, 1: {"status_code": "temp_current"}},
    )


def test_specs_tipos_acesso_escala_e_dp(sl):
    specs = sl.specs_from_device(_dev())
    assert specs["switch_led"].type == "bool" and specs["switch_led"].access == "rw"
    assert specs["switch_led"].dp_id == 20
    assert specs["work_mode"].access == "w" and specs["work_mode"].range == ["white", "colour"]
    t = specs["temp_current"]
    assert (t.type, t.access, t.scale, t.unit, t.dp_id) == ("value", "r", 1, "°C", 1)
    assert t.to_ha(253) == 25.3


def test_raw_compativel_com_from_api(sl, models):
    raw = sl.raw_from_device(_dev())
    dev = models.MwTuyaDevice.from_api(raw, None)
    assert dev.device_id == "dev1" and dev.local_key == "0123456789abcdef"
    assert dev.status["switch_led"] is True


def test_qr_payload(sl):
    assert sl.qr_payload("abc") == "tuyaSmart--qrLogin?token=abc"
