"""Push em tempo real via Tuya Message Service (Pulsar sobre WebSocket).

Substitui o polling de 30 s da nuvem: cada mudança de DP chega em ~1 s.
Exige o *Message Service* habilitado no projeto Tuya IoT. Uma conexão por
Access ID; várias contas do mesmo projeto compartilham a mesma conexão.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import aiohttp
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_LOGGER = logging.getLogger(__name__)

PULSAR_PORT = 8285
QUERY = "?ackTimeoutMillis=3000&subscriptionType=Failover"
HEARTBEAT = 30
BACKOFF_MAX = 300

Listener = Callable[[dict[str, Any]], None]


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def pulsar_url(base_url: str, access_id: str, topic: str = "event") -> str:
    """`https://openapi.tuyaus.com` → `wss://mqe.tuyaus.com:8285/ws/v2/consumer/...`."""
    host = urlparse(base_url).hostname or "openapi.tuyaus.com"
    host = host.replace("openapi", "mqe", 1)
    if host.startswith("openapi-"):
        host = "mqe" + host[len("openapi") :]
    return (
        f"wss://{host}:{PULSAR_PORT}/ws/v2/consumer/persistent/"
        f"{access_id}/out/{topic}/{access_id}-sub{QUERY}"
    )


def pulsar_password(access_id: str, secret: str) -> str:
    return _md5(access_id + _md5(secret))[8:24]


def decrypt_payload(data: str, secret: str, model: str | None = None) -> dict[str, Any]:
    """Decifra o campo `data` (AES-128-ECB legado ou AES-GCM)."""
    raw = base64.b64decode(data)
    key = secret[8:24].encode()
    if model and "gcm" in model.lower():
        plain = AESGCM(key).decrypt(raw[:12], raw[12:], None)
    else:
        dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        plain = dec.update(raw) + dec.finalize()
        plain = plain[: -plain[-1]]
    return json.loads(plain.decode())


def parse_message(text: str, secret: str) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
    """Retorna (message_id, evento decifrado ou None, propriedades)."""
    envelope = json.loads(text)
    msg_id = str(envelope.get("messageId") or "")
    props = envelope.get("properties") or {}
    try:
        payload = json.loads(base64.b64decode(envelope.get("payload") or ""))
        model = payload.get("encryptModel") or payload.get("decryptModel") or props.get("em")
        event = decrypt_payload(payload["data"], secret, model)
        event.setdefault("_protocol", payload.get("protocol"))
    except (ValueError, KeyError, TypeError) as err:
        _LOGGER.debug("Mensagem Tuya ignorada (%s)", err)
        event = None
    return msg_id, event, props


def status_from_event(event: dict[str, Any]) -> tuple[str, dict[str, Any], bool | None]:
    """Extrai (device_id, {code: value}, online) de um evento Pulsar.

    Protocolo 4 = relatório de DPs; protocolo 20 / `bizCode` = online/offline.
    """
    did = str(event.get("devId") or (event.get("bizData") or {}).get("devId") or "")
    status: dict[str, Any] = {}
    for item in event.get("status") or []:
        if isinstance(item, dict) and "code" in item:
            status[str(item["code"])] = item.get("value")
    online: bool | None = None
    biz = str(event.get("bizCode") or "")
    if biz == "online":
        online = True
    elif biz == "offline":
        online = False
    elif status:
        online = True
    return did, status, online


class TuyaPushHub:
    """Conexão Pulsar compartilhada por Access ID."""

    def __init__(
        self, session: aiohttp.ClientSession, base_url: str, access_id: str, secret: str
    ) -> None:
        self._session = session
        self._url = pulsar_url(base_url, access_id)
        self._access_id = access_id
        self._secret = secret
        self._listeners: set[Listener] = set()
        self._task: asyncio.Task | None = None
        self.connected = False
        self.denied = False
        self.messages = 0

    def add_listener(self, listener: Listener) -> Callable[[], None]:
        self._listeners.add(listener)
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(
                self._run(), name=f"mw_tuya_push_{self._access_id[:6]}"
            )

        def _remove() -> None:
            self._listeners.discard(listener)
            if not self._listeners:
                self.stop()

        return _remove

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self.connected = False

    async def _run(self) -> None:
        backoff = 5
        headers = {
            "username": self._access_id,
            "password": pulsar_password(self._access_id, self._secret),
        }
        while self._listeners:
            try:
                async with self._session.ws_connect(
                    self._url, headers=headers, heartbeat=HEARTBEAT, timeout=15
                ) as ws:
                    self.connected, self.denied, backoff = True, False, 5
                    _LOGGER.info("MW Tuya: push em tempo real conectado")
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            break
                        msg_id, event, _ = parse_message(msg.data, self._secret)
                        if msg_id:
                            await ws.send_str(json.dumps({"messageId": msg_id}))
                        if event:
                            self.messages += 1
                            for listener in list(self._listeners):
                                try:
                                    listener(event)
                                except Exception:
                                    _LOGGER.exception("Listener de push falhou")
            except asyncio.CancelledError:
                raise
            except aiohttp.WSServerHandshakeError as err:
                self.denied = err.status in (401, 403)
                _LOGGER.warning(
                    "MW Tuya: push recusado (%s) — habilite o Message Service no projeto Tuya IoT",
                    err.status,
                )
                backoff = BACKOFF_MAX
            except (aiohttp.ClientError, TimeoutError, OSError) as err:
                _LOGGER.debug("MW Tuya: push desconectado (%s)", err)
            self.connected = False
            await asyncio.sleep(backoff)
            backoff = min(BACKOFF_MAX, backoff * 2)


_HUBS: dict[str, TuyaPushHub] = {}


def get_hub(
    session: aiohttp.ClientSession, base_url: str, access_id: str, secret: str
) -> TuyaPushHub:
    hub = _HUBS.get(access_id)
    if hub is None:
        hub = _HUBS[access_id] = TuyaPushHub(session, base_url, access_id, secret)
    return hub


async def async_close_hubs() -> None:
    for hub in _HUBS.values():
        hub.stop()
    with contextlib.suppress(Exception):
        _HUBS.clear()
