"""Protocolo Local Tuya (TCP 6668 v3.3/v3.4 + Descoberta LAN UDP 6666/6667).

Adaptado de `mw_infrared/local.py` e `tuya-local-sync` sem dependências externas:
usa `cryptography` (já embarcada no Home Assistant).

Regra de ouro para estabilidade local:
**Uma conexão TCP por comando/consulta, e fecha.** Dispositivos Tuya aceitam
uma única conexão TCP por vez; manter socket aberto trava o aplicativo Tuya e
derruba conexões concorrentes. Abrir, enviar e fechar leva ~60-150 ms.
"""

from __future__ import annotations

import asyncio
import binascii
import contextlib
import hashlib
import json
import logging
import socket
import struct
import time
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)

PREFIX = 0x000055AA
SUFFIX = 0x0000AA55
CMD_CONTROL = 0x07
CMD_STATUS = 0x08
CMD_DP_QUERY = 0x0A
PORT_TCP = 6668
PORT_UDP_PLAIN = 6666
PORT_UDP_ENC = 6667

HEADER_33 = b"3.3" + b"\x00" * 12
UDP_KEY = hashlib.md5(b"yGAdlopoPVldABfn").digest()


class TuyaLocalError(RuntimeError):
    """Falha ao comunicar com o dispositivo Tuya na rede local."""


def _encrypt_ecb(key: bytes, data: bytes) -> bytes:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _decrypt_ecb(key: bytes, data: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    raw = decryptor.update(data) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    try:
        return unpadder.update(raw) + unpadder.finalize()
    except ValueError:
        return raw


class TuyaLocalClient:
    """Cliente local TCP 6668 para um dispositivo Tuya com `local_key`."""

    def __init__(
        self,
        host: str,
        device_id: str,
        local_key: str,
        version: str = "3.3",
        timeout: float = 4.0,
    ) -> None:
        self.host = host.strip()
        self.device_id = device_id.strip()
        self._key = local_key.strip().encode("utf-8")
        self.version = version.strip() or "3.3"
        self.timeout = timeout
        self._seq = 0
        self._lock = asyncio.Lock()
        self.last_error: str = ""

    def _frame(self, cmd: int, payload: bytes) -> bytes:
        self._seq += 1
        body = struct.pack(">IIII", PREFIX, self._seq, cmd, len(payload) + 8) + payload
        crc = binascii.crc32(body) & 0xFFFFFFFF
        return body + struct.pack(">II", crc, SUFFIX)

    def _control_payload(self, dps: dict[str, Any], node_id: str = "") -> bytes:
        body: dict[str, Any] = {
            "devId": self.device_id,
            "uid": self.device_id,
            "t": str(int(time.time())),
            "dps": {str(k): v for k, v in dps.items()},
        }
        if node_id:
            body["cid"] = node_id
        message = json.dumps(body, separators=(",", ":")).encode("utf-8")
        return HEADER_33 + _encrypt_ecb(self._key, message)

    def _query_payload(self, node_id: str = "") -> bytes:
        body: dict[str, Any] = {
            "gwId": self.device_id,
            "devId": self.device_id,
            "uid": self.device_id,
            "t": str(int(time.time())),
        }
        if node_id:
            body["cid"] = node_id
        message = json.dumps(body, separators=(",", ":")).encode("utf-8")
        return _encrypt_ecb(self._key, message)

    @staticmethod
    def _parse(data: bytes) -> list[dict[str, Any]]:
        frames: list[dict[str, Any]] = []
        offset = 0
        while offset + 20 <= len(data):
            head = data.find(struct.pack(">I", PREFIX), offset)
            if head < 0 or head + 16 > len(data):
                break
            _, seq, cmd, length = struct.unpack(">IIII", data[head : head + 16])
            end = head + 16 + length
            if end > len(data):
                break
            body = data[head + 16 : end - 8]
            retcode = 0
            if len(body) >= 4 and body[:4] == b"\x00\x00\x00\x00":
                retcode = 0
                body = body[4:]
            frames.append({"seq": seq, "cmd": cmd, "retcode": retcode, "body": body})
            offset = end
        return frames

    async def async_set_dps(
        self, dps: dict[str, Any], node_id: str = "", attempts: int = 2
    ) -> bool:
        """Envia comando de escrita de DPs via TCP 6668 local."""
        last_err: Exception | None = None
        for attempt in range(max(1, attempts)):
            if attempt:
                await asyncio.sleep(0.25 * attempt)
            try:
                return await self._set_dps_once(dps, node_id=node_id)
            except TuyaLocalError as err:
                last_err = err
                self.last_error = str(err)
        raise last_err if last_err else TuyaLocalError(f"{self.host}: falha desconhecida")

    async def _set_dps_once(self, dps: dict[str, Any], node_id: str = "") -> bool:
        async with self._lock:
            writer = None
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, PORT_TCP), timeout=self.timeout
                )
                writer.write(self._frame(CMD_CONTROL, self._control_payload(dps, node_id=node_id)))
                await writer.drain()
                try:
                    data = await asyncio.wait_for(reader.read(2048), timeout=self.timeout)
                except TimeoutError:
                    self.last_error = ""
                    return True
                frames = self._parse(data)
                if frames:
                    self.last_error = ""
                return bool(frames)
            except (TimeoutError, OSError) as err:
                raise TuyaLocalError(f"{self.host}: {err}") from err
            finally:
                if writer is not None:
                    writer.close()
                    with contextlib.suppress(Exception):
                        await writer.wait_closed()

    async def async_get_dps(self, node_id: str = "") -> dict[str, Any] | None:
        """Consulta estado atual dos DPs via TCP 6668 local."""
        async with self._lock:
            writer = None
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, PORT_TCP), timeout=self.timeout
                )
                writer.write(self._frame(CMD_DP_QUERY, self._query_payload(node_id=node_id)))
                await writer.drain()
                data = await asyncio.wait_for(reader.read(4096), timeout=self.timeout)
            except (TimeoutError, OSError) as err:
                raise TuyaLocalError(f"{self.host}: {err}") from err
            finally:
                if writer is not None:
                    writer.close()
                    with contextlib.suppress(Exception):
                        await writer.wait_closed()

        for frame in self._parse(data):
            body = frame["body"]
            if not body:
                continue
            if body.startswith((b"3.3", b"3.4")):
                body = body[15:]
            for candidate in (body, None):
                if candidate is None:
                    break
                try:
                    parsed = json.loads(_decrypt_ecb(self._key, candidate))
                except Exception:
                    try:
                        parsed = json.loads(candidate)
                    except Exception:
                        continue
                if isinstance(parsed, dict) and "dps" in parsed:
                    self.last_error = ""
                    return dict(parsed["dps"])
        return None

    async def async_ping(self) -> bool:
        """Verifica se o dispositivo aceita conexão TCP na porta 6668."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, PORT_TCP), timeout=self.timeout
            )
        except (TimeoutError, OSError):
            return False
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return True


def decode_udp_broadcast_packet(data: bytes) -> dict[str, Any] | None:
    """Decodifica um pacote de anúncio UDP Tuya (porta 6666 em claro ou 6667 AES-ECB)."""
    if len(data) < 28:
        return None
    prefix = struct.unpack(">I", data[:4])[0]
    if prefix != PREFIX:
        return None
    body = data[20:-8]
    if not body:
        return None
    for raw in (body, _try_decrypt_udp(body)):
        if not raw:
            continue
        try:
            text = raw.decode("utf-8", errors="ignore").strip("\x00")
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                parsed = json.loads(text[start : end + 1])
                if isinstance(parsed, dict) and ("gwId" in parsed or "ip" in parsed):
                    return parsed
        except Exception:
            continue
    return None


def _try_decrypt_udp(body: bytes) -> bytes | None:
    try:
        return _decrypt_ecb(UDP_KEY, body)
    except Exception:
        return None


class _UdpDiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, found: dict[str, dict[str, Any]]) -> None:
        self._found = found

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        info = decode_udp_broadcast_packet(data)
        if not info:
            return
        gw_id = str(info.get("gwId") or "")
        ip = str(info.get("ip") or addr[0])
        version = str(info.get("version") or "3.3")
        if gw_id and ip:
            self._found[gw_id] = {
                "ip": ip,
                "version": version,
                "productKey": str(info.get("productKey") or ""),
            }


async def async_discover_lan_devices(timeout: float = 2.5) -> dict[str, dict[str, Any]]:
    """Escuta pacotes UDP de anúncio Tuya nas portas 6666 e 6667 durante `timeout` segundos."""
    found: dict[str, dict[str, Any]] = {}
    loop = asyncio.get_running_loop()
    transports: list[asyncio.BaseTransport] = []

    for port in (PORT_UDP_PLAIN, PORT_UDP_ENC):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with contextlib.suppress(AttributeError, OSError):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.setblocking(False)
        try:
            sock.bind(("", port))
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _UdpDiscoveryProtocol(found), sock=sock
            )
            transports.append(transport)
        except OSError as err:
            _LOGGER.debug("Porta UDP %s indisponível para descoberta LAN: %s", port, err)
            sock.close()

    if transports:
        await asyncio.sleep(timeout)
        for tr in transports:
            tr.close()

    return found
