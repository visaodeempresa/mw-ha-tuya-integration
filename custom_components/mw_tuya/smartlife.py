"""Canal Smart Life (login por QR Code) — o mesmo da integração Tuya nativa.

Usa o `tuya-device-sharing-sdk` (já presente no HA por causa da Tuya nativa):
- sem a cota de "controllable device pool" do projeto Tuya IoT;
- push MQTT em tempo real;
- `local_key`, mapa dp_id ⇄ código e especificação dos DPs;
- cenas e vídeo das câmeras.

O SDK é síncrono (requests + paho em thread); tudo aqui roda no executor e
os eventos voltam ao loop do HA com `call_soon_threadsafe`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from tuya_sharing import (
    CustomerDevice,
    LoginControl,
    Manager,
    SharingDeviceListener,
    SharingTokenListener,
)

from .dpspec import UNIT_FIX, DpSpec

_LOGGER = logging.getLogger(__name__)
logging.getLogger("tuya_sharing").setLevel(logging.CRITICAL)

# Credencial pública do app "Home Assistant" na Tuya (a mesma da integração nativa)
SL_CLIENT_ID = "HA_3y9q4ak7g4ephrvke"
SL_SCHEMA = "haauthorize"
SPEC_WORKERS = 8

TYPE_MAP = {
    "boolean": "bool",
    "integer": "value",
    "enum": "enum",
    "json": "string",
    "string": "string",
    "raw": "raw",
    "bitmap": "bitmap",
}


def qr_payload(token: str) -> str:
    return f"tuyaSmart--qrLogin?token={token}"


def request_qr(user_code: str) -> tuple[bool, dict[str, Any]]:
    """(executor) Pede um QR de login para o User Code do app Smart Life/Tuya."""
    res = LoginControl().qr_code(SL_CLIENT_ID, SL_SCHEMA, user_code)
    ok = bool(res.get("success"))
    return ok, (res.get("result") or {}) if ok else res


def poll_login(qr_token: str, user_code: str) -> tuple[bool, dict[str, Any]]:
    """(executor) Resultado do QR escaneado → dados para guardar na entrada."""
    ok, info = LoginControl().login_result(qr_token, SL_CLIENT_ID, user_code)
    if not ok:
        return False, info
    return True, {
        "user_code": user_code,
        "terminal_id": info["terminal_id"],
        "endpoint": info["endpoint"],
        "username": info.get("username") or "",
        "token_info": {
            "t": info["t"],
            "uid": info["uid"],
            "expire_time": info["expire_time"],
            "access_token": info["access_token"],
            "refresh_token": info["refresh_token"],
        },
    }


def specs_from_device(device: CustomerDevice) -> dict[str, DpSpec]:
    """`function` (escrita) + `status_range` (leitura) + `local_strategy` (dp_id)."""
    dp_of: dict[str, int] = {}
    for dp_id, item in (getattr(device, "local_strategy", None) or {}).items():
        code = (item or {}).get("status_code")
        if code and str(dp_id).isdigit():
            dp_of[str(code)] = int(dp_id)

    out: dict[str, DpSpec] = {}
    readable = getattr(device, "status_range", None) or {}
    writable = getattr(device, "function", None) or {}
    for code in {*readable, *writable}:
        src = writable.get(code) or readable.get(code)
        try:
            values = json.loads(getattr(src, "values", "") or "{}")
        except (TypeError, ValueError):
            values = {}
        if not isinstance(values, dict):
            values = {}
        unit = values.get("unit")
        unit = UNIT_FIX.get(unit, unit) if isinstance(unit, str) else None
        access = ("r" if code in readable else "") + ("w" if code in writable else "")
        out[code] = DpSpec(
            code=code,
            dp_id=dp_of.get(code),
            access=access or "r",
            type=TYPE_MAP.get(str(getattr(src, "type", "")).lower(), "raw"),
            min=values.get("min", 0) or 0,
            max=values.get("max", 0) or 0,
            scale=int(values.get("scale", 0) or 0),
            step=values.get("step", 1) or 1,
            unit=unit,
            range=[str(x) for x in values.get("range") or []],
            label=[str(x) for x in values.get("label") or []],
        )
    return out


def raw_from_device(device: CustomerDevice) -> dict[str, Any]:
    """Converte para o formato de `/v1.0/users/{uid}/devices` (reuso de `from_api`)."""
    return {
        "id": device.id,
        "name": getattr(device, "name", "") or device.id,
        "category": getattr(device, "category", "") or "",
        "product_id": getattr(device, "product_id", "") or "",
        "product_name": getattr(device, "product_name", "") or "",
        "online": bool(getattr(device, "online", False)),
        "local_key": getattr(device, "local_key", "") or "",
        "node_id": getattr(device, "node_id", "") or "",
        "sub": bool(getattr(device, "sub", False)),
        "status": [{"code": c, "value": v} for c, v in (device.status or {}).items()],
    }


class _TokenListener(SharingTokenListener):
    def __init__(self, on_token: Callable[[dict[str, Any]], None]) -> None:
        self._on_token = on_token

    def update_token(self, token_info: dict[str, Any]) -> None:
        self._on_token(
            {k: token_info[k] for k in ("t", "uid", "expire_time", "access_token", "refresh_token")}
        )


class _DeviceListener(SharingDeviceListener):
    def __init__(self, on_status: Callable[[str, dict[str, Any], bool | None], None]) -> None:
        self._on_status = on_status

    def update_device(
        self,
        device: CustomerDevice,
        updated_status_properties: list[str] | None = None,
        dp_timestamps: dict | None = None,
    ) -> None:
        props = updated_status_properties or []
        status = {c: device.status.get(c) for c in props if c in device.status}
        self._on_status(device.id, status, bool(getattr(device, "online", True)))

    def add_device(self, device: CustomerDevice) -> None:
        return

    def remove_device(self, device_id: str) -> None:
        return


class SmartLifeSession:
    """Sessão Smart Life de uma conta (thread-safe pelo executor do HA)."""

    def __init__(
        self,
        data: dict[str, Any],
        on_token: Callable[[dict[str, Any]], None],
    ) -> None:
        self.username = str(data.get("username") or "")
        self.manager = Manager(
            SL_CLIENT_ID,
            data["user_code"],
            data["terminal_id"],
            data["endpoint"],
            data["token_info"],
            _TokenListener(on_token),
        )
        self._listener: _DeviceListener | None = None

    @property
    def devices(self) -> dict[str, CustomerDevice]:
        return self.manager.device_map

    @property
    def mq_connected(self) -> bool:
        mq = self.manager.mq
        client = getattr(mq, "client", None)
        try:
            return bool(client and client.is_connected())
        except Exception:
            return mq is not None

    # ---------------------------------------------------------------- catálogo (executor)
    def load(self, selected: set[str]) -> None:
        """Lista casas e aparelhos; detalha (spec + estratégia local) só os selecionados."""
        mgr = self.manager
        api = mgr.customer_api
        repo = mgr.device_repository
        mgr.user_homes = mgr.home_repository.query_homes()
        found: dict[str, CustomerDevice] = {}
        for home in mgr.user_homes:
            resp = api.get("/v1.0/m/life/ha/home/devices", {"homeId": home.id})
            if not resp.get("success"):
                continue
            for item in resp.get("result") or []:
                dev = CustomerDevice(**item)
                dev.status = {
                    s["code"]: s["value"]
                    for s in (item.get("status") or [])
                    if isinstance(s, dict) and "code" in s and "value" in s
                }
                found[dev.id] = dev

        def _detail(dev: CustomerDevice) -> None:
            try:
                repo.update_device_specification(dev)
                repo.update_device_strategy_info(dev)
            except Exception as err:
                _LOGGER.debug("Smart Life: detalhe de %s falhou: %s", dev.id, err)
            dev.set_up = True

        chosen = [d for d in found.values() if d.id in selected]
        with ThreadPoolExecutor(SPEC_WORKERS) as pool:
            list(pool.map(_detail, chosen))
        mgr.device_map.clear()
        mgr.device_map.update(found)

    def scenes(self) -> list[Any]:
        return self.manager.query_scenes()

    def homes(self) -> dict[str, str]:
        return {str(h.id): str(h.name) for h in self.manager.user_homes}

    # ---------------------------------------------------------------- comandos (executor)
    def send(self, device_id: str, commands: list[dict[str, Any]]) -> bool:
        # Direto na API: o `send_commands` do SDK descarta repetições em 10 s
        res = self.manager.customer_api.post(
            f"/v1.1/m/thing/{device_id}/commands", None, {"commands": commands}
        )
        if not res.get("success"):
            raise SmartLifeError(f"[{res.get('code')}] {res.get('msg')}")
        return True

    def trigger_scene(self, home_id: str, scene_id: str) -> None:
        self.manager.trigger_scene(home_id, scene_id)

    def stream_url(self, device_id: str, kind: str = "rtsp") -> str | None:
        return self.manager.get_device_stream_allocate(device_id, kind)

    # ---------------------------------------------------------------- push (executor)
    def start_push(self, on_status: Callable[[str, dict[str, Any], bool | None], None]) -> None:
        if self._listener:
            self.manager.remove_device_listener(self._listener)
        self._listener = _DeviceListener(on_status)
        self.manager.add_device_listener(self._listener)
        self.manager.refresh_mq()

    def stop(self) -> None:
        if self._listener:
            self.manager.remove_device_listener(self._listener)
            self._listener = None
        if self.manager.mq is not None:
            self.manager.mq.stop()
            self.manager.mq = None


class SmartLifeError(RuntimeError):
    """Falha reportada pelo canal Smart Life."""
