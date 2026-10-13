"""Protocolo do Message Service (Pulsar): URL, senha, decifragem e extração de status."""

from __future__ import annotations

import base64
import importlib
import json

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SECRET = "0123456789abcdefFEDCBA9876543210"
AID = "accessid123"


@pytest.fixture(scope="module")
def push(models):
    return importlib.import_module("mwtuya.push")


def _ecb(obj: dict) -> str:
    padder = padding.PKCS7(128).padder()
    raw = padder.update(json.dumps(obj).encode()) + padder.finalize()
    enc = Cipher(algorithms.AES(SECRET[8:24].encode()), modes.ECB()).encryptor()
    return base64.b64encode(enc.update(raw) + enc.finalize()).decode()


def _gcm(obj: dict) -> str:
    nonce = b"\x01" * 12
    ct = AESGCM(SECRET[8:24].encode()).encrypt(nonce, json.dumps(obj).encode(), None)
    return base64.b64encode(nonce + ct).decode()


def _envelope(data: str, **extra) -> str:
    payload = {"data": data, "protocol": 4, **extra}
    return json.dumps(
        {"messageId": "m1", "payload": base64.b64encode(json.dumps(payload).encode()).decode()}
    )


def test_url_por_regiao(push):
    url = push.pulsar_url("https://openapi.tuyaus.com", AID)
    assert url.startswith(f"wss://mqe.tuyaus.com:8285/ws/v2/consumer/persistent/{AID}/out/event/")
    assert url.endswith("subscriptionType=Failover")
    assert "mqe.tuyaeu.com" in push.pulsar_url("https://openapi.tuyaeu.com", AID)


def test_senha_md5_trecho_8_24(push):
    assert len(push.pulsar_password(AID, SECRET)) == 16


EVENT = {"devId": "dev1", "status": [{"code": "switch_1", "value": True, "t": 1}]}


@pytest.mark.parametrize("modelo", [None, "aes_gcm"])
def test_decifra_ecb_e_gcm(push, modelo):
    data = _gcm(EVENT) if modelo else _ecb(EVENT)
    extra = {"encryptModel": modelo} if modelo else {}
    msg_id, event, _ = push.parse_message(_envelope(data, **extra), SECRET)
    assert msg_id == "m1"
    assert push.status_from_event(event) == ("dev1", {"switch_1": True}, True)


def test_online_offline_por_bizcode(push):
    did, status, online = push.status_from_event(
        {"bizCode": "offline", "bizData": {"devId": "dev9"}}
    )
    assert (did, status, online) == ("dev9", {}, False)


def test_mensagem_corrompida_nao_quebra(push):
    msg_id, event, _ = push.parse_message(_envelope("bm9wZQ=="), SECRET)
    assert msg_id == "m1" and event is None
