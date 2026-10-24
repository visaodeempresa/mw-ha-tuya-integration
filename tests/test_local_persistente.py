"""Testes da conexão persistente do TuyaLocalDevice (TCP 6668).

Nasceu do defeito medido em 24/10/2026: conexão efêmera por comando media
6–21 s em rajada (o aparelho Tuya recusa conexão nova nos segundos depois de
fechar a anterior) — as luzes do escritório demoravam até 22 s para acender.
O aparelho precisa ver UMA conexão, mantida, reaproveitada por comando e
leitura; falha de transporte derruba o socket e o próximo comando reconecta.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import sys
import types
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
COMPONENTE = RAIZ / "custom_components" / "mw_tuya"

if "mwtuya" not in sys.modules:
    _pkg = types.ModuleType("mwtuya")
    _pkg.__path__ = [str(COMPONENTE)]
    sys.modules["mwtuya"] = _pkg
_local = importlib.import_module("mwtuya.local")

TuyaLocalDevice = _local.TuyaLocalDevice
TuyaLocalError = _local.TuyaLocalError

CHAVE = "0123456789abcdef"


class _ServidorTuya:
    """Servidor TCP que conta conexões e responde um chunk a cada frame lido."""

    def __init__(self) -> None:
        self.conexoes = 0
        self.comandos = 0
        self.fechar_apos_resposta = False
        self._server: asyncio.Server | None = None
        self._clientes: list[asyncio.StreamWriter] = []

    async def iniciar(self, *, fechar_apos_resposta: bool = False) -> int:
        self.fechar_apos_resposta = fechar_apos_resposta
        self._server = await asyncio.start_server(self._atender, "127.0.0.1", 0)
        return self._server.sockets[0].getsockname()[1]

    async def _atender(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.conexoes += 1
        self._clientes.append(writer)
        try:
            while True:
                data = await reader.read(2048)
                if not data:
                    return
                self.comandos += 1
                writer.write(b"ok")
                await writer.drain()
                if self.fechar_apos_resposta:
                    writer.close()
                    return
        except (ConnectionError, OSError):
            return

    async def parar(self) -> None:
        for w in self._clientes:
            with contextlib.suppress(Exception):
                w.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()


def _cliente(porta: int) -> TuyaLocalDevice:
    return TuyaLocalDevice(
        host="127.0.0.1",
        device_id="ebtestedevice0001",
        local_key=CHAVE,
        version="3.3",
        port=porta,
    )


def _rodar(coro):
    return asyncio.run(coro)


async def _reaproveita_o_mesmo_socket_em_rajada():
    """Dois comandos seguidos usam UMA conexão — sem reconnect por comando."""
    srv = _ServidorTuya()
    porta = await srv.iniciar()
    try:
        cli = _cliente(porta)
        assert await cli.async_set_dps({"20": True}) is True
        assert await cli.async_set_dps({"20": False}) is True
        await cli.async_close()
        assert srv.conexoes == 1
        assert srv.comandos == 2
    finally:
        await srv.parar()


async def _reconecta_apos_socket_morto():
    """Aparelho fechou a conexão: o próximo comando abre conexão nova e vai a bom porto."""
    srv = _ServidorTuya()
    porta = await srv.iniciar(fechar_apos_resposta=True)
    try:
        cli = _cliente(porta)
        assert await cli.async_set_dps({"20": True}) is True
        await asyncio.sleep(0.1)
        assert await cli.async_set_dps({"20": False}) is True
        await cli.async_close()
        assert srv.conexoes == 2
    finally:
        await srv.parar()


async def _async_close_libera_o_socket():
    """async_close fecha de verdade (unload não deixa socket pendurado)."""
    srv = _ServidorTuya()
    porta = await srv.iniciar()
    try:
        cli = _cliente(porta)
        assert await cli.async_set_dps({"20": True}) is True
        await cli.async_close()
        await asyncio.sleep(0.1)
        assert cli._writer is None and cli._session_key is None
    finally:
        await srv.parar()


async def _ping_reaproveita_socket_aberto():
    """Ping não abre conexão nova quando o socket já está vivo."""
    srv = _ServidorTuya()
    porta = await srv.iniciar()
    try:
        cli = _cliente(porta)
        assert await cli.async_set_dps({"20": True}) is True
        assert await cli.async_ping() is True
        assert srv.conexoes == 1
        await cli.async_close()
    finally:
        await srv.parar()


def test_reaproveita_o_mesmo_socket_em_rajada(local):
    _rodar(_reaproveita_o_mesmo_socket_em_rajada())


def test_reconecta_apos_socket_morto(local):
    _rodar(_reconecta_apos_socket_morto())


def test_async_close_libera_o_socket(local):
    _rodar(_async_close_libera_o_socket())


def test_ping_reaproveita_socket_aberto(local):
    _rodar(_ping_reaproveita_socket_aberto())


def test_chave_invalida_continua_erro(local):
    cli = TuyaLocalDevice(
        host="127.0.0.1", device_id="ebtestedevice0002", local_key="curta", version="3.3"
    )
    with pytest.raises(TuyaLocalError):
        _rodar(cli.async_set_dps({"20": True}))
