"""Disponibiliza `security`, `models` e `local` para testes unitários sem o Home Assistant instalado."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
COMPONENTE = RAIZ / "custom_components" / "mw_tuya"


def _pacote():
    if "mwtuya" not in sys.modules:
        pkg = types.ModuleType("mwtuya")
        pkg.__path__ = [str(COMPONENTE)]
        sys.modules["mwtuya"] = pkg
    return sys.modules["mwtuya"]


@pytest.fixture(scope="session")
def security():
    _pacote()
    return importlib.import_module("mwtuya.security")


@pytest.fixture(scope="session")
def models():
    _pacote()
    return importlib.import_module("mwtuya.models")


@pytest.fixture(scope="session")
def local():
    _pacote()
    return importlib.import_module("mwtuya.local")
