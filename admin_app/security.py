"""密码、JWT、CSRF、脱敏等安全工具。

JWT 用标准库实现 HS256，避免为一个演示后台引入额外依赖；
密码优先 Argon2id，缺失时降级为 scrypt（两者都不可逆）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any

from . import config

# ---------- 密码 ----------
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    _PH = PasswordHasher()
    ARGON2_AVAILABLE = True
except Exception:  # pragma: no cover - 环境缺包时走 scrypt
    _PH = None
    ARGON2_AVAILABLE = False


def hash_password(password: str) -> str:
    """生成不可逆密码哈希。"""
    if ARGON2_AVAILABLE and _PH is not None:
        return _PH.hash(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password_hash: str, password: str) -> bool:
    """校验密码；任何异常都视为失败，避免时序与异常差异泄露信息。"""
    try:
        if password_hash.startswith("scrypt$"):
            _, salt_hex, digest_hex = password_hash.split("$", 2)
            calc = hashlib.scrypt(
                password.encode("utf-8"),
                salt=bytes.fromhex(salt_hex),
                n=2**14, r=8, p=1, dklen=32,
            )
            return hmac.compare_digest(calc.hex(), digest_hex)
        if _PH is not None:
            return _PH.verify(password_hash, password)
    except (VerifyMismatchError, ValueError, TypeError):
        return False
    return False


# ---------- JWT ----------
def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def create_access_token(subject: str, role: str, lanes: list[str], ttl_minutes: int | None = None) -> str:
    """签发 HS256 JWT；role 仅用于展示，真实权限每次从数据库取。"""
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "lanes": lanes,
        "iat": now,
        "exp": now + (ttl_minutes or config.TOKEN_TTL_MINUTES) * 60,
        "jti": secrets.token_hex(8),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    head = _b64encode(json.dumps(header, separators=(",", ":")).encode())
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{head}.{body}".encode("ascii")
    signature = hmac.new(config.SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{head}.{body}.{_b64encode(signature)}"


def decode_access_token(token: str) -> dict[str, Any] | None:
    """验签 + 过期校验；失败返回 None，不抛异常。"""
    try:
        head, body, sig = token.split(".")
        expected = hmac.new(
            config.SECRET_KEY.encode("utf-8"), f"{head}.{body}".encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _b64decode(sig)):
            return None
        payload = json.loads(_b64decode(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


# ---------- CSRF ----------
def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_valid(cookie_value: str | None, form_value: str | None) -> bool:
    """双提交校验：Cookie 与表单值必须一致。"""
    if not cookie_value or not form_value:
        return False
    return hmac.compare_digest(cookie_value, form_value)


# ---------- 脱敏 ----------
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_PLATE_RE = re.compile(r"[\u4e00-\u9fa5][A-Z][A-Z0-9]{5,6}")


def mask_pii(text: str) -> tuple[str, int]:
    """脱敏手机号、身份证、车牌；返回脱敏文本与命中次数。"""
    hits = 0

    def _phone(m: re.Match) -> str:
        nonlocal hits
        hits += 1
        return m.group(0)[:3] + "****" + m.group(0)[-4:]

    def _id(m: re.Match) -> str:
        nonlocal hits
        hits += 1
        return m.group(0)[:4] + "**********" + m.group(0)[-4:]

    def _plate(m: re.Match) -> str:
        nonlocal hits
        hits += 1
        return m.group(0)[:2] + "***" + m.group(0)[-1:]

    masked = _PHONE_RE.sub(_phone, text)
    masked = _ID_RE.sub(_id, masked)
    masked = _PLATE_RE.sub(_plate, masked)
    return masked, hits


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def locked_hash(text: str) -> str:
    """锁定段哈希：忽略行尾空白与空行差异，防止无意义的哈希漂移。"""
    normalized = "\n".join(line.strip() for line in text.strip().splitlines() if line.strip())
    return sha256_text(normalized)
