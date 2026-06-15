import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any


PASSWORD_ALGORITHM = "pbkdf2_sha256"
TOKEN_ALGORITHM = "HS256"


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def hash_password(password: str, *, salt: bytes | None = None, iterations: int = 260000) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PASSWORD_ALGORITHM}${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = _b64decode(salt_text)
        expected_digest = _b64decode(digest_text)
    except (TypeError, ValueError):
        return False

    actual_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual_digest, expected_digest)


def read_password_hash(configured_hash: str, password_hash_file: str = "") -> str:
    if password_hash_file:
        path = Path(password_hash_file)
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    return configured_hash


def write_password_hash(encoded: str, password_hash_file: str) -> None:
    if not password_hash_file:
        raise ValueError("Password hash file is not configured")
    path = Path(password_hash_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{encoded}\n", encoding="utf-8")
    path.chmod(0o600)


def create_access_token(username: str, secret: str, expires_hours: int) -> str:
    now = int(time.time())
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + max(expires_hours, 1) * 3600,
        "typ": "access",
    }
    header = {"alg": TOKEN_ALGORITHM, "typ": "JWT"}
    signing_input = ".".join((_json_segment(header), _json_segment(payload)))
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64encode(signature)}"


def verify_access_token(token: str, secret: str) -> str | None:
    try:
        header_segment, payload_segment, signature_segment = token.split(".", 2)
        signing_input = f"{header_segment}.{payload_segment}"
        expected_signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64decode(signature_segment), expected_signature):
            return None
        header = _json_loads(header_segment)
        payload = _json_loads(payload_segment)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    if header.get("alg") != TOKEN_ALGORITHM or payload.get("typ") != "access":
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    username = payload.get("sub")
    return username if isinstance(username, str) and username else None


def _json_segment(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _b64encode(raw)


def _json_loads(segment: str) -> dict[str, Any]:
    value = json.loads(_b64decode(segment).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Token segment must be a JSON object")
    return value
