import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import Header, HTTPException

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
TOKEN_TTL_HOURS = int(os.environ.get("TOKEN_TTL_HOURS", "24"))


def _sign(message: str) -> str:
    return hmac.new(JWT_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": int(time.time()) + TOKEN_TTL_HOURS * 3600,
    }
    msg = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{msg}.{_sign(msg)}"


def verify_token(token: str) -> dict[str, Any] | None:
    try:
        msg, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(_sign(msg), sig):
            return None
        padded = msg + "=" * (-len(msg) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except (ValueError, json.JSONDecodeError):
        return None


def authenticate(username: str, password: str) -> bool:
    return hmac.compare_digest(username, ADMIN_USER) and hmac.compare_digest(
        password, ADMIN_PASSWORD
    )


def require_admin(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ", 1)[1].strip()
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return str(payload.get("sub", ""))
