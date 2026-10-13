"""Testes unitários do protocolo local Tuya 3.3 (TCP 6668 e UDP 6666/6667)."""

from __future__ import annotations

import binascii
import json
import struct


def test_quadro_tcp_prefixo_sufixo_e_crc(local):
    cli = local.TuyaLocalClient("192.168.1.50", "d" * 20, "k" * 16)
    quadro = cli._frame(local.CMD_CONTROL, b"payload")
    assert struct.unpack(">I", quadro[:4])[0] == local.PREFIX
    assert struct.unpack(">I", quadro[-4:])[0] == local.SUFFIX
    assert struct.unpack(">I", quadro[12:16])[0] == len(b"payload") + 8
    assert struct.unpack(">I", quadro[-8:-4])[0] == binascii.crc32(quadro[:-8])


def test_payload_controle_leva_cabecalho_33_e_aes_multiplo_16(local):
    cli = local.TuyaLocalClient("192.168.1.50", "d" * 20, "0123456789abcdef")
    carga = cli._control_payload({"1": True})
    assert carga[:3] == b"3.3"
    assert len(carga[:15]) == 15
    assert (len(carga) - 15) % 16 == 0


def test_decodificacao_pacote_udp_broadcast_criptografado(local):
    anuncio = json.dumps({"ip": "192.168.1.88", "gwId": "eb123456789", "version": "3.3"}).encode(
        "utf-8"
    )
    cifrado = local._encrypt_ecb(local.UDP_KEY, anuncio)
    cabecalho = struct.pack(">IIII", local.PREFIX, 0, 0x13, len(cifrado) + 12) + b"\x00\x00\x00\x00"
    pacote = cabecalho + cifrado + struct.pack(">II", 0, local.SUFFIX)
    decodificado = local.decode_udp_broadcast_packet(pacote)
    assert decodificado is not None
    assert decodificado["gwId"] == "eb123456789"
    assert decodificado["ip"] == "192.168.1.88"
    assert decodificado["version"] == "3.3"
