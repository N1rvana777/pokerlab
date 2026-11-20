"""OIDC fail-closed validation and app-owned credential persistence."""
import base64
import json
import os
import time

import pytest

from pokerstudio.agent.auth import ISSUER, SiwcAuth, _dpapi, validate_identity


def b64(value):
    if isinstance(value, dict):
        value = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


@pytest.fixture
def signed_identity():
    cryptography = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_numbers()
    jwks = {"keys": [{"kid": "test", "kty": "RSA", "e": b64(public.e.to_bytes(3, "big")),
                       "n": b64(public.n.to_bytes(256, "big"))}]}
    def make(**changes):
        claims = {"iss": ISSUER, "aud": "oaiapp_test", "sub": "test-user", "iat": time.time(),
                  "exp": time.time() + 1000, "nonce": "test-nonce", **changes}
        value = b64({"alg": "RS256", "kid": "test"}) + "." + b64(claims)
        signature = private.sign(value.encode(), padding.PKCS1v15(), hashes.SHA256())
        return value + "." + b64(signature)
    return make, jwks


def test_oidc_signature_issuer_audience_time_nonce(signed_identity):
    make, keys = signed_identity
    valid = dict(client_id="oaiapp_test", nonce="test-nonce", jwks=keys)
    assert validate_identity(make(), **valid)["sub"] == "test-user"
    for changes in ({"iss": "https://attacker.test"}, {"aud": "other-client"}, {"exp": 0},
                    {"iat": time.time() + 10000}, {"nonce": "wrong"}, {"sub": ""}):
        with pytest.raises(RuntimeError, match="身份验证失败"):
            validate_identity(make(**changes), **valid)
    token = make()
    head, body, sig = token.split(".")
    with pytest.raises(RuntimeError):
        validate_identity(head + "." + b64({"sub": "attacker"}) + "." + sig, **valid)


def test_callback_missing_mismatched_expired_reused_state_is_rejected(tmp_path):
    auth = SiwcAuth(tmp_path)
    with pytest.raises(RuntimeError, match="过期"):
        auth.complete({"state": "missing"})
    auth.pending = {"state": "correct", "expires_at": time.time() + 60, "client_id": "dynamic_agent_client"}
    with pytest.raises(RuntimeError, match="state"):
        auth.complete({"state": "wrong"})
    assert auth.pending is not None
    with pytest.raises(RuntimeError, match="client_id"):
        auth.complete({"state": "correct", "code": "invalid", "client_id": "dynamic_agent_client"})
    assert auth.pending is None
    with pytest.raises(RuntimeError, match="过期"):
        auth.complete({"state": "correct"})


@pytest.mark.skipif(os.name != "nt", reason="Windows user-scoped DPAPI")
def test_dpapi_keeps_plain_credentials_out_of_file(tmp_path):
    auth = SiwcAuth(tmp_path)
    auth.record = {"access_token": "private-access-credential", "refresh_token": "private-refresh-credential",
                   "expires_at": time.time() + 3600, "scopes": ["chatgpt.tokens.use.direct"]}
    auth._persist()
    protected = (tmp_path / "chatgpt.dpapi").read_bytes()
    assert b"private-access-credential" not in protected
    restored = SiwcAuth(tmp_path)
    assert restored.access_token() == "private-access-credential"
    assert "access_token" not in restored.status()
    restored.logout()
    assert not (tmp_path / "chatgpt.dpapi").exists()
