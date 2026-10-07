from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from .db import Database


PIN_ITERATIONS = 240_000
SESSION_TTL_SECONDS = 8 * 60 * 60


def hash_pin(pin: str, salt: bytes | None = None) -> str:
    if salt is None:
        salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, PIN_ITERATIONS)
    return f"pbkdf2_sha256${PIN_ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_pin(pin: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.pbkdf2_hmac(
            "sha256", pin.encode("utf-8"), salt, int(iterations_text)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def initialize_auth(database: Database) -> None:
    if database.get_setting("pin_hash") is None:
        database.set_setting("pin_hash", hash_pin("1234"))


def authenticate_pin(database: Database, pin: str) -> bool:
    encoded = database.get_setting("pin_hash") or ""
    return verify_pin(pin, encoded)


def change_pin(database: Database, new_pin: str) -> None:
    if not new_pin.isdigit() or len(new_pin) < 4 or len(new_pin) > 12:
        raise ValueError("PIN musi zawierać od 4 do 12 cyfr")
    database.set_setting("pin_hash", hash_pin(new_pin))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_session(database: Database, scope: str = "edit", ttl_seconds: int = SESSION_TTL_SECONDS) -> str:
    payload = {
        "exp": int(time.time()) + ttl_seconds,
        "nonce": secrets.token_hex(8),
        "scope": scope,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    secret = (database.get_setting("session_secret") or "").encode()
    signature = _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def validate_session(database: Database, token: str | None, scope: str = "edit") -> bool:
    if not token or "." not in token:
        return False
    body, signature = token.split(".", 1)
    secret = (database.get_setting("session_secret") or "").encode()
    expected = _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        payload: dict[str, Any] = json.loads(_unb64(body))
        return int(payload["exp"]) >= int(time.time()) and payload.get("scope") == scope
    except (ValueError, KeyError, json.JSONDecodeError):
        return False
