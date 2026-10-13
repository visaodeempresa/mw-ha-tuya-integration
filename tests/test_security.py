"""Testes unitários do construtor de assinatura HMAC-SHA256 e do TokenManager."""

from __future__ import annotations


def test_empty_body_sha256_constante(security):
    builder = security.SignatureBuilder("cid_123", "sec_456")
    s2s = builder.build_string_to_sign("GET", "/v1.0/token", {"grant_type": "1"})
    linhas = s2s.splitlines()
    assert linhas[0] == "GET"
    assert linhas[1] == security.EMPTY_BODY_SHA256
    assert linhas[3] == "/v1.0/token?grant_type=1"


def test_query_params_ordenados_alfabeticamente(security):
    builder = security.SignatureBuilder("cid_123", "sec_456")
    s2s = builder.build_string_to_sign("GET", "/v1.0/devices", {"z": "9", "a": "1"})
    assert s2s.endswith("/v1.0/devices?a=1&z=9")


def test_hmac_sha256_sempre_uppercase(security):
    builder = security.SignatureBuilder("cid_123", "sec_456")
    s2s = builder.build_string_to_sign("GET", "/v1.0/token", {"grant_type": "1"})
    assinatura = builder.calculate_sign("1700000000000", s2s)
    assert len(assinatura) == 64
    assert assinatura == assinatura.upper()


def test_token_manager_ciclo_de_vida(security):
    tm = security.TokenManager()
    assert not tm.is_valid
    tm.store("tok_abc", "ref_xyz", expire_time_seconds=7200)
    assert tm.is_valid
    assert tm.access_token == "tok_abc"
    tm.invalidate()
    assert not tm.is_valid
    assert tm.access_token is None
