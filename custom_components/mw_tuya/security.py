"""Assinatura HMAC-SHA256 (Tuya Sign v2.0) e gestão de token por conta.

Adaptado do módulo `core.security.signature_builder` e `core.client.token_manager`
do projeto `mcp-smarthome`, sem dependências externas ao Home Assistant.
"""

from __future__ import annotations

import hashlib
import hmac
import time

EMPTY_BODY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
EXPIRY_SAFETY_MARGIN_SECONDS = 120


class SignatureBuilder:
    """Construtor de assinaturas HMAC-SHA256 para a Tuya Cloud OpenAPI v2.0."""

    def __init__(self, client_id: str, secret: str) -> None:
        self.client_id = client_id.strip()
        self._secret = secret.strip()

    @staticmethod
    def sha256_hash(content: str | bytes) -> str:
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def hmac_sha256(key: str, message: str) -> str:
        return (
            hmac.new(
                key=key.encode("utf-8"),
                msg=message.encode("utf-8"),
                digestmod=hashlib.sha256,
            )
            .hexdigest()
            .upper()
        )

    def build_string_to_sign(
        self,
        method: str,
        path: str,
        query_params: dict[str, str] | None = None,
        body: str | bytes = "",
        signature_headers: dict[str, str] | None = None,
    ) -> str:
        content_sha256 = self.sha256_hash(body) if body else EMPTY_BODY_SHA256

        headers_str = ""
        if signature_headers:
            for key in sorted(signature_headers.keys()):
                headers_str += f"{key}:{signature_headers[key]}\n"

        url = path
        if query_params:
            sorted_params = sorted(query_params.items())
            query_string = "&".join(f"{k}={v}" for k, v in sorted_params)
            url = f"{path}?{query_string}"

        return f"{method.upper()}\n{content_sha256}\n{headers_str}\n{url}"

    def calculate_sign(
        self,
        timestamp: str,
        string_to_sign: str,
        access_token: str = "",
        nonce: str = "",
    ) -> str:
        message = self.client_id + access_token + timestamp + nonce + string_to_sign
        return self.hmac_sha256(self._secret, message)


class TokenManager:
    """Cache isolado de `access_token` por conta Tuya."""

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0

    @property
    def access_token(self) -> str | None:
        return self._access_token

    @property
    def is_valid(self) -> bool:
        if not self._access_token:
            return False
        return time.monotonic() < (self._expires_at - EXPIRY_SAFETY_MARGIN_SECONDS)

    def store(
        self,
        access_token: str,
        refresh_token: str = "",
        expire_time_seconds: int = 7200,
    ) -> None:
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._expires_at = time.monotonic() + max(60, int(expire_time_seconds))

    def invalidate(self) -> None:
        self._access_token = None
        self._refresh_token = None
        self._expires_at = 0.0
