"""Transporte Local Tuya (TCP 6668, protocolos 3.3, 3.4 e 3.5 + descoberta UDP 6666/6667/7000).

Implementa:
- **Conexão efêmera por comando (`open -> negotiate/send -> close`)**: dispositivos Tuya
  aceitam apenas 1 socket TCP por vez; abrir e fechar por operação (~80–180 ms) evita
  travar o aparelho ou disputar conexão.
- **Protocolo 3.3**: Quadro `0x000055AA ... CRC32 + 0x0000AA55`, AES-128-ECB PKCS7,
  cabeçalho `b"3.3" + 12 zeros` em `CMD_CONTROL (0x07)`.
- **Protocolo 3.4**: Quadro `0x000055AA ... HMAC-SHA256(32B) + 0x0000AA55`, negociação
  de chave de sessão em 3 passos (`0x03 -> 0x04 -> 0x05`), AES-128-ECB PKCS7 e
  `CMD_CONTROL_NEW (0x0D)` / `CMD_DP_QUERY_NEW (0x10)`.
- **Protocolo 3.5**: Quadro `0x00006699 ... IV(12B) + Ciphertext + Tag(16B) + 0x00009966`,
  negociação de chave de sessão em 3 passos (`0x03 -> 0x04 -> 0x05`) com AES-128-GCM.
- **Descoberta passiva UDP (`6666`, `6667`, `7000`)**: Decodifica broadcasts 3.1, 3.3,
  3.4 (`0x000055AA`) e 3.5 (`0x00006699` AES-GCM) na LAN.
"""

from __future__ import annotations

import asyncio
import binascii
import contextlib
import hashlib
import hmac
import json
import logging
import os
import struct
import time
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)

PREFIX_55AA = 0x000055AA
SUFFIX_55AA = 0x0000AA55
PREFIX_6699 = 0x00006699
SUFFIX_6699 = 0x00009966
PREFIX_55AA_BYTES = b"\x00\x00\x55\xaa"
PREFIX_6699_BYTES = b"\x00\x00\x66\x99"
SUFFIX_6699_BYTES = b"\x00\x00\x99\x66"

HEADER_55AA_FMT = ">IIII"
HEADER_6699_FMT = ">IHIII"

CMD_SESS_KEY_NEG_START = 0x03
CMD_SESS_KEY_NEG_RESP = 0x04
CMD_SESS_KEY_NEG_FINISH = 0x05
CMD_CONTROL = 0x07
CMD_DP_QUERY = 0x0A
CMD_CONTROL_NEW = 0x0D
CMD_DP_QUERY_NEW = 0x10

NO_PROTOCOL_HEADER_CMDS = {
    CMD_DP_QUERY,
    CMD_DP_QUERY_NEW,
    CMD_SESS_KEY_NEG_START,
    CMD_SESS_KEY_NEG_RESP,
    CMD_SESS_KEY_NEG_FINISH,
}

TCP_PORT = 6668
UDP_PORTS = (6666, 6667, 7000)

# Chave MD5 fixa usada pela Tuya para cifrar os pacotes UDP de broadcast (6667 / 7000)
UDP_BROADCAST_KEY = hashlib.md5(b"yGAdlopoPVldABfn").digest()

HEADER_33 = b"3.3" + b"\x00" * 12
HEADER_34 = b"3.4" + b"\x00" * 12
HEADER_35 = b"3.5" + b"\x00" * 12


class TuyaLocalError(RuntimeError):
    """Falha na comunicação local via TCP 6668."""


@dataclass(slots=True)
class DiscoveredLocalDevice:
    """Metadados de um dispositivo Tuya descoberto via UDP broadcast."""

    device_id: str
    ip: str
    version: str = "3.3"
    product_key: str = ""


def encrypt_aes_ecb(key: bytes, data: bytes, *, pad: bool = True) -> bytes:
    """Cifra `data` em AES-128-ECB (com ou sem PKCS7)."""
    payload = data
    if pad:
        padder = padding.PKCS7(128).padder()
        payload = padder.update(data) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(payload) + encryptor.finalize()


def decrypt_aes_ecb(key: bytes, data: bytes, *, unpad: bool = True) -> bytes:
    """Decifra `data` em AES-128-ECB (com ou sem PKCS7)."""
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    raw = decryptor.update(data) + decryptor.finalize()
    if not unpad:
        return raw
    unpadder = padding.PKCS7(128).unpadder()
    try:
        return unpadder.update(raw) + unpadder.finalize()
    except ValueError:
        return raw


def encrypt_aes_gcm(
    key: bytes,
    raw: bytes,
    iv: bytes,
    header: bytes | None = None,
) -> tuple[bytes, bytes]:
    """Cifra `raw` em AES-128-GCM retornando `(ciphertext, tag_16b)`."""
    encryptor = Cipher(algorithms.AES(key), modes.GCM(iv)).encryptor()
    if header:
        encryptor.authenticate_additional_data(header)
    ciphertext = encryptor.update(raw) + encryptor.finalize()
    return ciphertext, encryptor.tag


def decrypt_aes_gcm(
    key: bytes,
    ciphertext: bytes,
    iv: bytes,
    tag: bytes,
    header: bytes | None = None,
) -> bytes:
    """Decifra `ciphertext` em AES-128-GCM validando `tag` e `header` (AAD)."""
    decryptor = Cipher(algorithms.AES(key), modes.GCM(iv, tag)).decryptor()
    if header:
        decryptor.authenticate_additional_data(header)
    return decryptor.update(ciphertext) + decryptor.finalize()


def pack_55aa_frame(
    seq: int,
    cmd: int,
    payload: bytes,
    hmac_key: bytes | None = None,
) -> bytes:
    """Empacota um quadro `0x000055AA` (CRC32 para v3.3 ou HMAC-SHA256 para v3.4)."""
    tail_len = 36 if hmac_key else 8
    header = struct.pack(HEADER_55AA_FMT, PREFIX_55AA, seq, cmd, len(payload) + tail_len)
    body = header + payload
    if hmac_key:
        digest = hmac.new(hmac_key, body, hashlib.sha256).digest()
        return body + digest + struct.pack(">I", SUFFIX_55AA)
    crc = binascii.crc32(body) & 0xFFFFFFFF
    return body + struct.pack(">II", crc, SUFFIX_55AA)


def pack_6699_frame(
    seq: int,
    cmd: int,
    payload: bytes,
    key: bytes,
    iv: bytes | None = None,
) -> bytes:
    """Empacota um quadro `0x00006699` (AES-128-GCM para v3.5)."""
    nonce = iv if (iv and len(iv) == 12) else os.urandom(12)
    msg_len = len(payload) + 12 + 16
    header = struct.pack(HEADER_6699_FMT, PREFIX_6699, 0, seq, cmd, msg_len)
    ciphertext, tag = encrypt_aes_gcm(key, payload, nonce, header=header[4:])
    return header + nonce + ciphertext + tag + struct.pack(">I", SUFFIX_6699)


def parse_55aa_frames(data: bytes) -> list[dict[str, Any]]:
    """Extrai todos os quadros `0x000055AA` contidos em `data`."""
    frames: list[dict[str, Any]] = []
    offset = 0
    while offset + 20 <= len(data):
        head = data.find(PREFIX_55AA_BYTES, offset)
        if head < 0 or head + 16 > len(data):
            break
        _, seq, cmd, length = struct.unpack(HEADER_55AA_FMT, data[head : head + 16])
        end = head + 16 + length
        if end > len(data):
            break
        raw_body = data[head + 16 : end]
        frames.append({"seq": seq, "cmd": cmd, "raw_body": raw_body})
        offset = end
    return frames


def parse_6699_frames(data: bytes, key: bytes) -> list[dict[str, Any]]:
    """Extrai e decifra todos os quadros `0x00006699` (v3.5) contidos em `data`."""
    frames: list[dict[str, Any]] = []
    offset = 0
    header_len = struct.calcsize(HEADER_6699_FMT)
    while offset + header_len + 20 <= len(data):
        head = data.find(PREFIX_6699_BYTES, offset)
        if head < 0 or head + header_len > len(data):
            break
        _, _unk, seq, cmd, length = struct.unpack(HEADER_6699_FMT, data[head : head + header_len])
        end = head + header_len + length + 4
        if end > len(data):
            break
        header = data[head : head + header_len]
        chunk = data[head + header_len : end - 4]
        iv = chunk[:12]
        tag = chunk[-16:]
        ciphertext = chunk[12:-16]
        try:
            plain = decrypt_aes_gcm(key, ciphertext, iv, tag, header=header[4:])
        except Exception:
            offset = end
            continue
        retcode = 0
        if len(plain) >= 4 and plain[:1] != b"{" and plain[:4] == b"\x00\x00\x00\x00":
            retcode = struct.unpack(">I", plain[:4])[0]
            plain = plain[4:]
        frames.append({"seq": seq, "cmd": cmd, "retcode": retcode, "body": plain})
        offset = end
    return frames


def decode_udp_broadcast(data: bytes) -> DiscoveredLocalDevice | None:
    """Decodifica um pacote UDP 6666/6667/7000 da Tuya e devolve `DiscoveredLocalDevice`."""
    payload_bytes: bytes | None = None
    if data[:4] == PREFIX_55AA_BYTES and len(data) >= 28:
        inner = data[20:-8]
        if data[8:12] == b"\x00\x00\x00\x00":
            payload_bytes = inner
        else:
            with contextlib.suppress(Exception):
                payload_bytes = decrypt_aes_ecb(UDP_BROADCAST_KEY, inner)
    elif data[:4] == PREFIX_6699_BYTES:
        frames = parse_6699_frames(data, UDP_BROADCAST_KEY)
        if frames:
            payload_bytes = frames[0]["body"].rstrip(b"\x00")
    if payload_bytes is None:
        with contextlib.suppress(Exception):
            payload_bytes = decrypt_aes_ecb(UDP_BROADCAST_KEY, data)
    if not payload_bytes:
        return None
    try:
        text = payload_bytes.decode("utf-8", errors="ignore").strip("\x00")
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        parsed = json.loads(text[start : end + 1])
    except ValueError:
        return None
    dev_id = parsed.get("gwId") or parsed.get("devId")
    ip = parsed.get("ip")
    if not dev_id or not ip:
        return None
    return DiscoveredLocalDevice(
        device_id=str(dev_id),
        ip=str(ip),
        version=str(parsed.get("version") or "3.3"),
        product_key=str(parsed.get("productKey") or ""),
    )


class _UdpDiscoveryProtocol(asyncio.DatagramProtocol):
    """Protocolo asyncio para escutar broadcasts UDP 6666, 6667 e 7000."""

    def __init__(self, found: dict[str, DiscoveredLocalDevice]) -> None:
        self._found = found

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        dev = decode_udp_broadcast(data)
        if dev is not None:
            if not dev.ip and addr:
                dev.ip = addr[0]
            self._found[dev.device_id] = dev


async def async_discover_local_devices(
    timeout: float = 3.5,
) -> dict[str, DiscoveredLocalDevice]:
    """Escuta portas UDP 6666, 6667 e 7000 por `timeout` segundos."""
    loop = asyncio.get_running_loop()
    found: dict[str, DiscoveredLocalDevice] = {}
    transports: list[asyncio.BaseTransport] = []
    kwargs: dict[str, Any] = {"reuse_port": True} if os.name != "nt" else {}

    for port in UDP_PORTS:
        try:
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _UdpDiscoveryProtocol(found),
                local_addr=("0.0.0.0", port),
                **kwargs,
            )
            transports.append(transport)
        except OSError as err:
            _LOGGER.debug("Não foi possível escutar UDP %s: %s", port, err)

    try:
        if transports:
            await asyncio.sleep(timeout)
    finally:
        for tr in transports:
            tr.close()

    return found


class TuyaLocalDevice:
    """Cliente TCP 6668 efêmero para controle local de um dispositivo Tuya (3.3, 3.4 e 3.5)."""

    def __init__(
        self,
        host: str,
        device_id: str,
        local_key: str,
        version: str = "3.3",
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.device_id = device_id
        self._real_key = local_key.encode("utf-8")
        self.version = version if version in ("3.1", "3.2", "3.3", "3.4", "3.5") else "3.3"
        self.timeout = timeout
        self._seq = 0
        self._lock = asyncio.Lock()
        self.last_error: str = ""

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _encode_packet(
        self,
        cmd: int,
        payload: bytes,
        session_key: bytes,
    ) -> bytes:
        seq = self._next_seq()
        if self.version == "3.5":
            body = payload
            if cmd not in NO_PROTOCOL_HEADER_CMDS:
                body = HEADER_35 + body
            return pack_6699_frame(seq, cmd, body, session_key)

        if self.version == "3.4":
            body = payload
            if cmd not in NO_PROTOCOL_HEADER_CMDS:
                body = HEADER_34 + body
            enc = encrypt_aes_ecb(session_key, body, pad=True)
            return pack_55aa_frame(seq, cmd, enc, hmac_key=session_key)

        # Protocolo 3.3 (padrão)
        enc = encrypt_aes_ecb(session_key, payload, pad=True)
        body = enc if cmd in NO_PROTOCOL_HEADER_CMDS else HEADER_33 + enc
        return pack_55aa_frame(seq, cmd, body, hmac_key=None)

    def _extract_response_bodies(self, data: bytes, session_key: bytes) -> list[tuple[int, bytes]]:
        """Devolve lista de `(cmd, body_decifrado)` a partir de bytes lidos do socket."""
        out: list[tuple[int, bytes]] = []
        if self.version == "3.5":
            for frame in parse_6699_frames(data, session_key):
                out.append((frame["cmd"], frame["body"]))
            return out

        tail_len = 36 if self.version == "3.4" else 8
        for frame in parse_55aa_frames(data):
            raw_body = frame["raw_body"]
            if len(raw_body) <= tail_len:
                continue
            inner = raw_body[:-tail_len]
            if len(inner) >= 4 and inner[:4] == b"\x00\x00\x00\x00":
                inner = inner[4:]
            if not inner:
                out.append((frame["cmd"], b""))
                continue
            if self.version == "3.4":
                with contextlib.suppress(Exception):
                    inner = decrypt_aes_ecb(session_key, inner, unpad=True)
            out.append((frame["cmd"], inner))
        return out

    async def _negotiate_session_key(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> bytes:
        """Executa o handshake de chave de sessão (0x03 -> 0x04 -> 0x05) para v3.4 e v3.5."""
        if self.version not in ("3.4", "3.5"):
            return self._real_key

        local_nonce = b"0123456789abcdef"
        pkt_start = self._encode_packet(CMD_SESS_KEY_NEG_START, local_nonce, self._real_key)
        writer.write(pkt_start)
        await writer.drain()

        data = await asyncio.wait_for(reader.read(2048), timeout=self.timeout)
        bodies = self._extract_response_bodies(data, self._real_key)
        resp_payload = next(
            (b for cmd, b in bodies if cmd == CMD_SESS_KEY_NEG_RESP and len(b) >= 48),
            None,
        )
        if resp_payload is None:
            raise TuyaLocalError(
                f"{self.host}: falha na negociação de chave de sessão ({self.version})"
            )

        remote_nonce = resp_payload[:16]
        expected_hmac = hmac.new(self._real_key, local_nonce, hashlib.sha256).digest()
        if resp_payload[16:48] != expected_hmac:
            raise TuyaLocalError(f"{self.host}: HMAC inválido na sessão ({self.version})")

        rkey_hmac = hmac.new(self._real_key, remote_nonce, hashlib.sha256).digest()
        pkt_finish = self._encode_packet(CMD_SESS_KEY_NEG_FINISH, rkey_hmac, self._real_key)
        writer.write(pkt_finish)
        await writer.drain()

        xored = bytes(a ^ b for a, b in zip(local_nonce, remote_nonce, strict=False))
        if self.version == "3.4":
            return encrypt_aes_ecb(self._real_key, xored, pad=False)
        cipher_gcm, _ = encrypt_aes_gcm(self._real_key, xored, local_nonce[:12])
        return cipher_gcm[:16]

    def _build_control_json(self, dps: dict[str, Any], node_id: str = "") -> bytes:
        now = int(time.time())
        if self.version in ("3.4", "3.5"):
            data_block: dict[str, Any] = {"dps": dps}
            if node_id:
                data_block["cid"] = node_id
            return json.dumps(
                {"protocol": 5, "t": now, "data": data_block},
                separators=(",", ":"),
            ).encode("utf-8")
        if node_id:
            return json.dumps(
                {"cid": node_id, "t": str(now), "dps": dps},
                separators=(",", ":"),
            ).encode("utf-8")
        return json.dumps(
            {
                "devId": self.device_id,
                "uid": self.device_id,
                "t": str(now),
                "dps": dps,
            },
            separators=(",", ":"),
        ).encode("utf-8")

    async def async_set_dps(
        self,
        dps: dict[str, Any],
        attempts: int = 2,
        node_id: str = "",
    ) -> bool:
        """Envia DPs ao dispositivo via TCP 6668 com auto-recuperação de versão do protocolo."""
        if len(self._real_key) != 16:
            raise TuyaLocalError(f"{self.device_id}: local_key inválida (len != 16)")
        last_err: Exception | None = None
        versions_to_try = [self.version]
        if self.version in ("3.4", "3.5"):
            versions_to_try.append("3.3")
        else:
            versions_to_try.append("3.4")

        orig_ver = self.version
        for ver in versions_to_try:
            self.version = ver
            for attempt in range(max(1, attempts)):
                if attempt:
                    await asyncio.sleep(0.2 * attempt)
                try:
                    if await self._set_dps_once(dps, node_id=node_id):
                        return True
                except TuyaLocalError as err:
                    last_err = err
                    self.last_error = str(err)
                except Exception as err:
                    last_err = err
                    self.last_error = str(err)
                    break
        self.version = orig_ver
        raise last_err if last_err else TuyaLocalError(f"{self.host}: falha desconhecida")

    async def _set_dps_once(self, dps: dict[str, Any], node_id: str = "") -> bool:
        async with self._lock:
            writer: asyncio.StreamWriter | None = None
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, TCP_PORT),
                    timeout=self.timeout,
                )
                session_key = await self._negotiate_session_key(reader, writer)
                cmd = CMD_CONTROL_NEW if self.version in ("3.4", "3.5") else CMD_CONTROL
                pkt = self._encode_packet(
                    cmd, self._build_control_json(dps, node_id=node_id), session_key
                )
                writer.write(pkt)
                await writer.drain()
                try:
                    data = await asyncio.wait_for(reader.read(2048), timeout=self.timeout)
                except TimeoutError:
                    self.last_error = ""
                    return True
                bodies = self._extract_response_bodies(data, session_key)
                if bodies or data:
                    self.last_error = ""
                    return True
                return False
            except (TimeoutError, OSError) as err:
                raise TuyaLocalError(f"{self.host}: {err}") from err
            finally:
                if writer is not None:
                    writer.close()
                    with contextlib.suppress(Exception):
                        await writer.wait_closed()

    async def async_get_dps(self, node_id: str = "") -> dict[str, Any] | None:
        """Consulta os DPs atuais via `DP_QUERY` com auto-recuperação de versão."""
        if len(self._real_key) != 16:
            return None
        orig_ver = self.version
        versions_to_try = [self.version]
        if self.version in ("3.4", "3.5"):
            versions_to_try.append("3.3")
        else:
            versions_to_try.append("3.4")

        for ver in versions_to_try:
            self.version = ver
            dps = await self._get_dps_once(node_id=node_id)
            if dps is not None:
                return dps
        self.version = orig_ver
        return None

    async def _get_dps_once(self, node_id: str = "") -> dict[str, Any] | None:
        async with self._lock:
            writer: asyncio.StreamWriter | None = None
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, TCP_PORT),
                    timeout=self.timeout,
                )
                session_key = await self._negotiate_session_key(reader, writer)
                if self.version in ("3.4", "3.5"):
                    cmd = CMD_DP_QUERY_NEW
                    q_obj: dict[str, Any] = {"data": {"cid": node_id}} if node_id else {}
                    q_bytes = json.dumps(q_obj, separators=(",", ":")).encode("utf-8")
                else:
                    cmd = CMD_DP_QUERY
                    q_obj = (
                        {"cid": node_id}
                        if node_id
                        else {"gwId": self.device_id, "devId": self.device_id}
                    )
                    q_bytes = json.dumps(q_obj, separators=(",", ":")).encode("utf-8")
                writer.write(self._encode_packet(cmd, q_bytes, session_key))
                await writer.drain()
                data = await asyncio.wait_for(reader.read(4096), timeout=self.timeout)
            except (TimeoutError, OSError, TuyaLocalError) as err:
                self.last_error = str(err)
                return None
            finally:
                if writer is not None:
                    writer.close()
                    with contextlib.suppress(Exception):
                        await writer.wait_closed()

        for _cmd, body in self._extract_response_bodies(data, session_key):
            if not body:
                continue
            for hdr in (HEADER_33, HEADER_34, HEADER_35):
                if body.startswith(hdr[:3]):
                    body = body[len(hdr) :]
                    break
            candidates = [body]
            if self.version not in ("3.4", "3.5"):
                with contextlib.suppress(Exception):
                    candidates.insert(0, decrypt_aes_ecb(session_key, body, unpad=True))
            for cand in candidates:
                try:
                    text = cand.decode("utf-8", errors="ignore")
                    s, e = text.find("{"), text.rfind("}")
                    if s < 0 or e <= s:
                        continue
                    parsed = json.loads(text[s : e + 1])
                except ValueError:
                    continue
                if isinstance(parsed, dict):
                    if isinstance(parsed.get("dps"), dict):
                        return parsed["dps"]
                    if isinstance(parsed.get("data"), dict) and isinstance(
                        parsed["data"].get("dps"), dict
                    ):
                        return parsed["data"]["dps"]
        return None

    async def async_ping(self) -> bool:
        """Verifica se a porta TCP 6668 responde no host local."""
        writer: asyncio.StreamWriter | None = None
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, TCP_PORT),
                timeout=min(self.timeout, 2.0),
            )
            return True
        except (TimeoutError, OSError):
            return False
        finally:
            if writer is not None:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()


async def async_discover_lan_devices(timeout: float = 3.5) -> dict[str, dict[str, str]]:
    """Devolve mapa `{device_id: {"ip": ..., "version": ..., "product_key": ...}}`."""
    found = await async_discover_local_devices(timeout=timeout)
    return {
        did: {"ip": d.ip, "version": d.version, "product_key": d.product_key}
        for did, d in found.items()
    }


# Aliases para compatibilidade com coordinator e testes unitários
TuyaLocalClient = TuyaLocalDevice
encrypt_ecb = encrypt_aes_ecb
decrypt_ecb = decrypt_aes_ecb
pack_55aa = pack_55aa_frame
parse_55aa = parse_55aa_frames
