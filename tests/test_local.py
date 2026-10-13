"""Testes unitários do protocolo local Tuya 3.3, 3.4 e 3.5 (TCP 6668 e UDP 6666/6667/7000)."""

from __future__ import annotations

import binascii
import json
import struct


def test_quadro_55aa_v33_prefixo_sufixo_e_crc32(local):
    quadro = local.pack_55aa_frame(1, local.CMD_CONTROL, b"payload", hmac_key=None)
    assert struct.unpack(">I", quadro[:4])[0] == local.PREFIX_55AA
    assert struct.unpack(">I", quadro[-4:])[0] == local.SUFFIX_55AA
    assert struct.unpack(">I", quadro[12:16])[0] == len(b"payload") + 8
    assert struct.unpack(">I", quadro[-8:-4])[0] == binascii.crc32(quadro[:-8])


def test_quadro_55aa_v34_hmac_sha256(local):
    key = b"0123456789abcdef"
    quadro = local.pack_55aa_frame(2, local.CMD_CONTROL_NEW, b"payload_34", hmac_key=key)
    assert struct.unpack(">I", quadro[:4])[0] == local.PREFIX_55AA
    assert struct.unpack(">I", quadro[-4:])[0] == local.SUFFIX_55AA
    assert struct.unpack(">I", quadro[12:16])[0] == len(b"payload_34") + 36


def test_quadro_6699_v35_aes_gcm_roundtrip(local):
    key = b"0123456789abcdef"
    iv = b"123456789012"
    plain = b'3.5\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00{"protocol":5,"data":{"dps":{"1":true}}}'
    pkt = local.pack_6699_frame(7, local.CMD_CONTROL_NEW, plain, key, iv=iv)
    assert pkt[:4] == local.PREFIX_6699_BYTES
    assert pkt[-4:] == local.SUFFIX_6699_BYTES
    frames = local.parse_6699_frames(pkt, key)
    assert len(frames) == 1
    assert frames[0]["seq"] == 7
    assert frames[0]["cmd"] == local.CMD_CONTROL_NEW
    assert frames[0]["body"] == plain


def test_decodificacao_pacote_udp_broadcast_55aa_e_6699(local):
    anuncio = json.dumps({"ip": "192.168.1.88", "gwId": "eb123456789", "version": "3.3"}).encode(
        "utf-8"
    )
    cifrado = local.encrypt_aes_ecb(local.UDP_BROADCAST_KEY, anuncio)
    cabecalho = (
        struct.pack(">IIII", local.PREFIX_55AA, 0, 0x13, len(cifrado) + 12) + b"\x00\x00\x00\x00"
    )
    pacote_55aa = cabecalho + cifrado + struct.pack(">II", 0, local.SUFFIX_55AA)
    dev_33 = local.decode_udp_broadcast(pacote_55aa)
    assert dev_33 is not None
    assert dev_33.device_id == "eb123456789"
    assert dev_33.ip == "192.168.1.88"
    assert dev_33.version == "3.3"

    anuncio_35 = json.dumps(
        {"ip": "192.168.2.34", "gwId": "eb07ae42491687fd313aiy", "version": "3.5"}
    ).encode("utf-8")
    pacote_6699 = local.pack_6699_frame(1, 0x22, anuncio_35, local.UDP_BROADCAST_KEY)
    dev_35 = local.decode_udp_broadcast(pacote_6699)
    assert dev_35 is not None
    assert dev_35.device_id == "eb07ae42491687fd313aiy"
    assert dev_35.ip == "192.168.2.34"
    assert dev_35.version == "3.5"
