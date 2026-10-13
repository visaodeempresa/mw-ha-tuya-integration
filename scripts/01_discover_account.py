#!/usr/bin/env python3
"""Audita dispositivos, `local_key` e cenas de uma conta Tuya Cloud OpenAPI (stdlib only).

Adaptado de `mcp-smarthome` e `tuya-local-sync/scripts/05_fetch_keys.py`.
Lê variáveis de `.env` (ou de `/Volumes/SSD-T1-01/CLAUDE-SSD/PROJECTS/mcp/mcp-smarthome/.env`)
e salva o inventário bruto em `output/account_catalog.json` (ignorado pelo git).
"""

import hashlib
import hmac
import json
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
OUT.mkdir(parents=True, exist_ok=True)


def load_env() -> dict[str, str]:
    env: dict[str, str] = dict(os.environ)
    for candidate in (
        ROOT / ".env",
        Path("/Volumes/SSD-T1-01/CLAUDE-SSD/PROJECTS/mcp/mcp-smarthome/.env"),
    ):
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip())
    return env


def sign(secret: str, msg: str) -> str:
    return hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest().upper()


def api_get(base: str, cid: str, secret: str, path: str, token: str = "") -> dict:
    t = str(int(time.time() * 1000))
    content_hash = hashlib.sha256(b"").hexdigest()
    string_to_sign = f"GET\n{content_hash}\n\n{path}"
    msg = cid + token + t + string_to_sign if token else cid + t + string_to_sign
    headers = {
        "client_id": cid,
        "sign": sign(secret, msg),
        "t": t,
        "sign_method": "HMAC-SHA256",
    }
    if token:
        headers["access_token"] = token
    req = urllib.request.Request(f"{base.rstrip('/')}{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> None:
    env = load_env()
    base = env.get("TUYA_BASE_URL", "https://openapi.tuyaus.com")
    cid = env["TUYA_CLIENT_ID"]
    secret = env["TUYA_SECRET"]
    uid = env["TUYA_UID"]

    tok = api_get(base, cid, secret, "/v1.0/token?grant_type=1")
    if not tok.get("success"):
        raise RuntimeError(f"Falha ao obter token: {tok}")
    token = tok["result"]["access_token"]

    resp = api_get(base, cid, secret, f"/v1.0/users/{uid}/devices", token)
    if not resp.get("success"):
        raise RuntimeError(f"Falha ao listar devices: {resp}")
    devices = resp["result"]
    if isinstance(devices, dict):
        devices = devices.get("devices") or devices.get("list") or []

    with_keys = sum(1 for d in devices if d.get("local_key"))
    online = sum(1 for d in devices if d.get("online"))
    print(f"[ok] {len(devices)} dispositivos ({online} online, {with_keys} com local_key)")

    target = OUT / "account_catalog.json"
    target.write_text(json.dumps({"uid": uid, "devices": devices}, indent=2, ensure_ascii=False))
    print(f"[ok] Catálogo salvo em {target}")


if __name__ == "__main__":
    main()
