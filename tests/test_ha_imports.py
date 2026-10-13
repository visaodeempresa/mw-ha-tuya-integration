"""Importa todos os módulos do componente contra o Home Assistant real.

Pega constantes/enums inexistentes (ex.: `SensorDeviceClass.CARBON_DIOXIDE`)
antes que cheguem ao HA do usuário como `setup_error`. É pulado quando o
pacote `homeassistant` não está instalado (job `qualidade`); roda no job
`home-assistant` do CI.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("homeassistant")

RAIZ = Path(__file__).resolve().parent.parent
COMPONENTE = RAIZ / "custom_components" / "mw_tuya"
MODULOS = sorted(p.stem for p in COMPONENTE.glob("*.py") if p.stem != "__init__")


@pytest.fixture(scope="module", autouse=True)
def _custom_components_no_path():
    sys.path.insert(0, str(RAIZ))
    yield
    sys.path.remove(str(RAIZ))


def test_pacote_importa():
    importlib.import_module("custom_components.mw_tuya")


@pytest.mark.parametrize("modulo", MODULOS)
def test_modulo_importa(modulo):
    importlib.import_module(f"custom_components.mw_tuya.{modulo}")


def test_plataformas_declaradas_existem():
    pkg = importlib.import_module("custom_components.mw_tuya")
    for plataforma in pkg.PLATFORMS:
        nome = getattr(plataforma, "value", plataforma)
        mod = importlib.import_module(f"custom_components.mw_tuya.{nome}")
        assert hasattr(mod, "async_setup_entry"), nome


def test_versao_minima_do_ha_declarada():
    hacs = json.loads((RAIZ / "hacs.json").read_text())
    assert hacs.get("homeassistant"), "hacs.json deve declarar a versão mínima do HA"
