"""App-owned SIWC public-client login. Never reads Codex auth.json.

Windows persistence uses user-scoped DPAPI. Other operating systems deliberately
keep credentials in memory until an OS credential-store adapter is supplied.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def request_json(url, form=None):
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(url, data=data, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Include only the OAuth error code; never echo authorization codes/tokens.
        try:
            code = json.loads(exc.read()).get("error", "http_error")
            if not isinstance(code, str):
                code = code.get("code", "http_error")
        except Exception:
            code = "http_error"
        raise RuntimeError(f"OpenAI 认证失败：HTTP {exc.code} / {code}") from None


def validate_identity(token, *, client_id, nonce, jwks, now=None):
    """Verify a published OpenAI RSA/EC key with cryptography, then OIDC claims."""
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    except ImportError:
        raise RuntimeError("SIWC 登录验证需要 cryptography：python -m pip install cryptography") from None
    try:
        head, body, signature = token.split(".")
        header = json.loads(_unb64(head))
        claims = json.loads(_unb64(body))
        key = next(k for k in jwks["keys"] if k.get("kid") == header.get("kid"))
        signed = (head + "." + body).encode("ascii")
        sig = _unb64(signature)
        if header.get("alg") == "RS256" and key.get("kty") == "RSA":
            public = rsa.RSAPublicNumbers(int.from_bytes(_unb64(key["e"]), "big"),
                                          int.from_bytes(_unb64(key["n"]), "big")).public_key()
            public.verify(sig, signed, padding.PKCS1v15(), hashes.SHA256())
        elif header.get("alg") == "ES256" and key.get("kty") == "EC" and key.get("crv") == "P-256":
            if len(sig) != 64:
                raise ValueError("bad signature size")
            public = ec.EllipticCurvePublicNumbers(int.from_bytes(_unb64(key["x"]), "big"),
                                                   int.from_bytes(_unb64(key["y"]), "big"), ec.SECP256R1()).public_key()
            public.verify(encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")),
                          signed, ec.ECDSA(hashes.SHA256()))
        else:
            raise ValueError("unsupported signature")
        now = time.time() if now is None else now
        audience = claims.get("aud")
        if claims.get("iss") != ISSUER or client_id not in (audience if isinstance(audience, list) else [audience]):
            raise ValueError("issuer/audience mismatch")
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise ValueError("missing subject")
        if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] <= now - 5:
            raise ValueError("expired")
        if not isinstance(claims.get("iat"), (int, float)) or claims["iat"] > now + 5:
            raise ValueError("invalid issued time")
        if claims.get("nbf", 0) > now + 5:
            raise ValueError("not yet valid")
        if nonce is not None and not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise ValueError("nonce mismatch")
        return claims
    except Exception:
        raise RuntimeError("OpenAI 身份验证失败（签名、issuer、audience、时间或 nonce 不符）。") from None


def _dpapi(data: bytes, decrypt=False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("此平台暂未配置系统凭据存储；登录凭据仅保留在内存。")
    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


class SiwcAuth:
    def __init__(self, auth_dir: Path):
        self.auth_dir = Path(auth_dir)
        self.record = None
        self.pending = None
        self.server = None
        self.last_error = None
        self.lock = threading.RLock()
        file = self.auth_dir / "chatgpt.dpapi"
        if os.name == "nt" and file.is_file():
            try:
                self.record = json.loads(_dpapi(file.read_bytes(), decrypt=True))
            except Exception:
                self.last_error = "应用自己的 ChatGPT 凭据无法解密，请重新登录。"

    def _persist(self):
        if os.name != "nt":
            return
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        target = self.auth_dir / "chatgpt.dpapi"
        temp = target.with_suffix(".tmp")
        temp.write_bytes(_dpapi(json.dumps(self.record).encode("utf-8")))
        temp.replace(target)

    def status(self):
        record = self.record or {}
        return {"logged_in": bool(record.get("access_token")), "mode": "siwc",
                "email": record.get("email"), "plan_usage_enabled": "chatgpt.tokens.use.direct" in record.get("scopes", []),
                "expires_at": record.get("expires_at"), "login_pending": bool(self.pending), "error": self.last_error}

    def begin(self):
        self.cancel()
        self.last_error = None
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        host_file = self.auth_dir / "host-id.txt"
        if not host_file.is_file():
            host_file.write_text("urn:uuid:" + str(uuid.uuid4()), encoding="utf-8")
        host_id = host_file.read_text(encoding="utf-8").strip()
        auth = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/auth/callback":
                    self.send_error(404)
                    return
                try:
                    auth.complete({k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()})
                    text = "Pokerstudio 登录已完成，请返回应用。"
                    status = 200
                except Exception as exc:
                    auth.last_error = str(exc)
                    text = "Pokerstudio 登录失败，请返回应用查看状态。"
                    status = 400
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(text.encode("utf-8"))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        callback = f"http://127.0.0.1:{self.server.server_port}/auth/callback"
        saved = self.record or {}
        client_id = saved.get("client_id", "dynamic_agent_client")
        self.pending = {"state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32),
                        "verifier": secrets.token_urlsafe(64), "redirect_uri": callback,
                        "client_id": client_id, "expires_at": time.time() + 600, "host_id": host_id}
        params = {"client_id": client_id, "ext_agent_host_id": host_id, "response_type": "code",
                  "redirect_uri": callback, "scope": SCOPES, "resource": RESOURCE,
                  "state": self.pending["state"], "nonce": self.pending["nonce"],
                  "code_challenge_method": "S256", "code_challenge": _b64(hashlib.sha256(self.pending["verifier"].encode()).digest())}
        if client_id == "dynamic_agent_client":
            params["agent_name_hint"] = "pokerstudio"
        threading.Thread(target=self.server.serve_forever, daemon=True, name="pokerstudio-oauth").start()
        # A timer closes abandoned listeners and removes PKCE/state from memory.
        timer = threading.Timer(600, self._expire)
        timer.daemon = True
        timer.start()
        return {"type": "siwc", "authUrl": ISSUER + "/api/accounts/authorize?" + urllib.parse.urlencode(params),
                "expiresIn": 600}

    def _expire(self):
        if self.pending and self.pending["expires_at"] <= time.time():
            self.last_error = "登录超时，请重新开始。"
            self.cancel()

    def complete(self, values):
        with self.lock:
            pending = self.pending
            if not pending or pending["expires_at"] <= time.time():
                raise RuntimeError("登录已过期或已使用。")
            if not secrets.compare_digest(values.get("state", ""), pending["state"]):
                raise RuntimeError("OAuth state 不匹配。")
            # Consume exactly once, including failures after a valid state.
            self.pending = None
        if values.get("error"):
            raise RuntimeError("ChatGPT 登录被拒绝：" + values["error"])
        issued = values.get("client_id", pending["client_id"])
        if issued == "dynamic_agent_client" or (pending["client_id"] != "dynamic_agent_client" and issued != pending["client_id"]):
            raise RuntimeError("注册没有返回匹配的正式 client_id。")
        if not values.get("code"):
            raise RuntimeError("OAuth 回调缺少授权码。")
        tokens = request_json(ISSUER + "/api/accounts/oauth/token", {
            "grant_type": "authorization_code", "client_id": issued, "code": values["code"],
            "code_verifier": pending["verifier"], "redirect_uri": pending["redirect_uri"], "resource": RESOURCE})
        identity = validate_identity(tokens.get("id_token", ""), client_id=issued, nonce=pending["nonce"],
                                     jwks=request_json(ISSUER + "/.well-known/jwks.json"))
        if self.record and self.record.get("subject") != identity["sub"]:
            raise RuntimeError("返回的身份与已选账号不同，请先退出应用账号。")
        scopes = tokens.get("scope", "").split()
        if "chatgpt.tokens.use.direct" not in scopes or not tokens.get("access_token"):
            raise RuntimeError("登录未授予 ChatGPT plan usage，请在授权页面允许使用订阅额度。")
        self.record = {**tokens, "subject": identity["sub"], "email": identity.get("email"),
                       "client_id": issued, "scopes": scopes, "ext_agent_host_id": pending["host_id"],
                       "expires_at": time.time() + float(tokens.get("expires_in", 3600))}
        self._persist()
        threading.Thread(target=self.cancel, daemon=True).start()

    def access_token(self):
        with self.lock:
            if not self.record:
                raise RuntimeError("尚未登录 Pokerstudio 的 ChatGPT 账号。")
            if self.record["expires_at"] < time.time() + 60:
                if not self.record.get("refresh_token"):
                    raise RuntimeError("ChatGPT 登录已过期，请重新登录。")
                tokens = request_json(ISSUER + "/api/accounts/oauth/token", {
                    "grant_type": "refresh_token", "client_id": self.record["client_id"],
                    "refresh_token": self.record["refresh_token"], "resource": RESOURCE})
                if "chatgpt.tokens.use.direct" not in tokens.get("scope", "").split():
                    raise RuntimeError("刷新后没有 ChatGPT plan usage 权限，请重新登录。")
                if tokens.get("id_token"):
                    identity = validate_identity(tokens["id_token"], client_id=self.record["client_id"], nonce=None,
                                                 jwks=request_json(ISSUER + "/.well-known/jwks.json"))
                    if identity["sub"] != self.record["subject"]:
                        raise RuntimeError("刷新返回的身份不匹配。")
                self.record.update(tokens)
                self.record["scopes"] = tokens["scope"].split()
                self.record["expires_at"] = time.time() + float(tokens.get("expires_in", 3600))
                self._persist()
            return self.record["access_token"]

    def cancel(self):
        self.pending = None
        if self.server:
            server, self.server = self.server, None
            server.shutdown()
            server.server_close()

    def logout(self):
        self.cancel()
        self.record = None
        file = self.auth_dir / "chatgpt.dpapi"
        file.unlink(missing_ok=True)
