"""Cliente assíncrono para a Tuya Cloud OpenAPI v2.0 (por conta).

Adaptado de `mcp_smarthome.integration.tuya.core.client.tuya_cloud_client`
e `mw_infrared/api.py`. Suporta:
- Autenticação HMAC-SHA256 e refresh automático de `access_token`
- Listagem completa de dispositivos da conta (`/v1.0/users/{uid}/devices`) com `local_key`
- Descoberta de casas (`/v1.0/users/{uid}/homes`) e cenas (`/v1.1/homes/{home_id}/scenes`)
- Envio de comandos de controle (`/v1.0/iot-03/devices/{device_id}/commands`)
- Disparo de cenas (`/v1.0/homes/{home_id}/scenes/{scene_id}/trigger`)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import aiohttp

from .models import MwTuyaDevice, MwTuyaScene
from .security import SignatureBuilder, TokenManager

_LOGGER = logging.getLogger(__name__)

AUTH_ERROR_CODES = {1004, 1010, 1011, 1012, 1013, 1106}
RATE_LIMIT_CODES = {1003}


class TuyaApiError(RuntimeError):
    """Erro retornado pela Tuya Cloud OpenAPI."""

    def __init__(self, code: int | None, msg: str, path: str) -> None:
        self.code = code
        self.msg = msg
        self.path = path
        super().__init__(f"[{code}] {msg} ({path})")


class TuyaAuthError(TuyaApiError):
    """Credenciais inválidas ou recusadas pela Tuya Cloud."""


class TuyaCloudClient:
    """Cliente isolado para uma conta Tuya Cloud OpenAPI."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        client_id: str,
        client_secret: str,
        uid: str,
    ) -> None:
        self._session = session
        self.base_url = base_url.rstrip("/")
        self.uid = uid.strip()
        self.signature_builder = SignatureBuilder(client_id=client_id, secret=client_secret)
        self.token_manager = TokenManager()
        self._lock = asyncio.Lock()

    async def _raw_request(
        self,
        method: str,
        path: str,
        query_params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        with_token: bool = True,
    ) -> dict[str, Any]:
        token = await self._ensure_token() if with_token else ""
        body_bytes = (
            b"" if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        )
        stamp = str(int(time.time() * 1000))

        string_to_sign = self.signature_builder.build_string_to_sign(
            method=method.upper(),
            path=path,
            query_params=query_params,
            body=body_bytes,
        )
        sign = self.signature_builder.calculate_sign(
            timestamp=stamp,
            string_to_sign=string_to_sign,
            access_token=token,
        )

        headers: dict[str, str] = {
            "client_id": self.signature_builder.client_id,
            "sign": sign,
            "t": stamp,
            "sign_method": "HMAC-SHA256",
        }
        if token:
            headers["access_token"] = token
        if body is not None:
            headers["Content-Type"] = "application/json"

        url = f"{self.base_url}{path}"
        if query_params:
            qs = "&".join(f"{k}={v}" for k, v in sorted(query_params.items()))
            url = f"{url}?{qs}"

        try:
            async with self._session.request(
                method.upper(),
                url,
                data=body_bytes or None,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=25),
            ) as resp:
                text = await resp.text()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise TuyaApiError(None, f"Falha de rede: {err}", path) from err

        try:
            data = json.loads(text)
        except ValueError as err:
            raise TuyaApiError(None, f"Resposta não-JSON: {text[:120]}", path) from err

        if not data.get("success"):
            code = data.get("code")
            msg = str(data.get("msg", "erro desconhecido"))
            if code in AUTH_ERROR_CODES:
                self.token_manager.invalidate()
                raise TuyaAuthError(code, msg, path)
            raise TuyaApiError(code, msg, path)

        return data

    async def _ensure_token(self) -> str:
        if self.token_manager.is_valid and self.token_manager.access_token:
            return self.token_manager.access_token
        data = await self._raw_request(
            "GET",
            "/v1.0/token",
            query_params={"grant_type": "1"},
            with_token=False,
        )
        result = data.get("result") or {}
        access_token = str(result.get("access_token") or "")
        if not access_token:
            raise TuyaAuthError(None, "Token ausente na resposta da Tuya", "/v1.0/token")
        self.token_manager.store(
            access_token=access_token,
            refresh_token=str(result.get("refresh_token") or ""),
            expire_time_seconds=int(result.get("expire_time", 7200)),
        )
        return access_token

    async def async_get(self, path: str, query_params: dict[str, str] | None = None) -> Any:
        async with self._lock:
            resp = await self._raw_request("GET", path, query_params=query_params)
            return resp.get("result")

    async def async_post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        async with self._lock:
            resp = await self._raw_request("POST", path, body=body or {})
            return resp.get("result")

    # ------------------------------------------------------------------ Catálogo
    async def async_list_raw_devices(self) -> list[dict[str, Any]]:
        """Busca todos os dispositivos da conta (incluindo `local_key`, `status`, `category`)."""
        result = await self.async_get(f"/v1.0/users/{self.uid}/devices")
        if isinstance(result, dict):
            result = result.get("devices") or result.get("list") or []
        return list(result or [])

    async def async_list_devices(
        self, lan_map: dict[str, dict[str, Any]] | None = None
    ) -> list[MwTuyaDevice]:
        raw_list = await self.async_list_raw_devices()
        lan = lan_map or {}
        devices: list[MwTuyaDevice] = []
        for item in raw_list:
            dev_id = str(item.get("id") or "")
            if not dev_id:
                continue
            devices.append(MwTuyaDevice.from_api(item, lan.get(dev_id)))
        devices.sort(key=lambda d: d.name.lower())
        return devices

    async def async_list_homes(self) -> list[dict[str, Any]]:
        """Retorna todas as casas (`homes`) associadas ao UID."""
        try:
            res = await self.async_get(f"/v1.0/users/{self.uid}/homes")
            if isinstance(res, list):
                return res
        except TuyaApiError as err:
            _LOGGER.debug("Não foi possível listar homes para %s: %s", self.uid, err)
        return []

    async def async_list_scenes(self) -> list[MwTuyaScene]:
        """Busca todas as cenas Tap-to-Run de todas as casas da conta."""
        homes = await self.async_list_homes()
        scenes: list[MwTuyaScene] = []
        seen: set[str] = set()

        for home in homes:
            home_id = str(home.get("home_id") or home.get("id") or "")
            home_name = str(home.get("name") or "")
            if not home_id:
                continue
            raw_scenes: list[dict[str, Any]] = []
            for endpoint in (
                f"/v1.1/homes/{home_id}/scenes",
                f"/v1.0/homes/{home_id}/scenes",
            ):
                try:
                    res = await self.async_get(endpoint)
                    if isinstance(res, list):
                        raw_scenes = res
                        break
                    if isinstance(res, dict) and isinstance(res.get("scenes"), list):
                        raw_scenes = res["scenes"]
                        break
                except TuyaApiError:
                    continue

            for item in raw_scenes:
                sid = str(item.get("scene_id") or item.get("id") or "")
                if not sid or sid in seen:
                    continue
                seen.add(sid)
                scenes.append(
                    MwTuyaScene(
                        scene_id=sid,
                        name=str(item.get("name") or sid).strip(),
                        home_id=home_id,
                        home_name=home_name,
                        enabled=bool(item.get("enabled", True)),
                        background=str(item.get("background") or ""),
                    )
                )

        scenes.sort(key=lambda s: s.name.lower())
        return scenes

    # ------------------------------------------------------------------ Comandos
    async def async_send_commands(self, device_id: str, commands: list[dict[str, Any]]) -> bool:
        """Envia comandos para um dispositivo pela nuvem Tuya."""
        payload = {"commands": commands}
        for path in (
            f"/v1.0/iot-03/devices/{device_id}/commands",
            f"/v1.0/devices/{device_id}/commands",
        ):
            try:
                res = await self.async_post(path, payload)
                return bool(res) if res is not None else True
            except TuyaApiError as err:
                last_err = err
                continue
        raise last_err  # type: ignore[misc]

    async def async_trigger_scene(self, home_id: str, scene_id: str) -> bool:
        """Dispara uma cena Tap-to-Run na nuvem Tuya."""
        res = await self.async_post(f"/v1.0/homes/{home_id}/scenes/{scene_id}/trigger", {})
        return bool(res) if res is not None else True
