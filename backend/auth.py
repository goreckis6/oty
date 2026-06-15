import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import Header, HTTPException, Request

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
TOKEN_TTL_HOURS = int(os.environ.get("TOKEN_TTL_HOURS", str(30 * 24)))
TOKEN_COOKIE = "yts_admin_session"
ADMIN_ALLOWED_IPS = os.environ.get("ADMIN_ALLOWED_IPS", "").strip()


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


def _password_configured() -> bool:
    return bool(ADMIN_PASSWORD) and ADMIN_PASSWORD != "admin" and len(ADMIN_PASSWORD) >= 8


def authenticate(password: str) -> bool:
    site_url = os.environ.get("SITE_URL", "")
    if site_url.startswith("https://") and not _password_configured():
        return False
    return hmac.compare_digest(password, ADMIN_PASSWORD)


def _normalize_ip(ip: str) -> str:
    ip = (ip or "").strip()
    if ip.startswith("::ffff:"):
        ip = ip[7:]
    return ip


def _is_private_or_loopback(ip: str) -> bool:
    ip = _normalize_ip(ip)
    if not ip:
        return False
    if ip in ("127.0.0.1", "::1", "localhost"):
        return True
    if ip.startswith("10."):
        return True
    if ip.startswith("192.168."):
        return True
    if ip.startswith("172."):
        parts = ip.split(".")
        if len(parts) == 4:
            try:
                second = int(parts[1])
                if 16 <= second <= 31:
                    return True
            except ValueError:
                pass
    return False


def client_ip(request: Request) -> str:
    peer = _normalize_ip(request.client.host if request.client else "")
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        candidate = _normalize_ip(forwarded.split(",")[0])
        if candidate and not _is_private_or_loopback(candidate):
            return candidate
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        candidate = _normalize_ip(real_ip)
        if candidate and not _is_private_or_loopback(candidate):
            return candidate
    if _is_private_or_loopback(peer):
        if forwarded:
            return _normalize_ip(forwarded.split(",")[0])
        if real_ip:
            return _normalize_ip(real_ip)
    return peer


def assert_admin_client(request: Request) -> None:
    if not ADMIN_ALLOWED_IPS:
        return
    allowed = {_normalize_ip(ip) for ip in ADMIN_ALLOWED_IPS.split(",") if ip.strip()}
    seen = client_ip(request)
    if seen not in allowed:
        raise HTTPException(status_code=404, detail="Not found")


def extract_token(request: Request, authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return request.cookies.get(TOKEN_COOKIE)


def require_admin(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    assert_admin_client(request)
    token = extract_token(request, authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    payload = verify_token(token)
    if not payload or payload.get("sub") != ADMIN_USER:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return ADMIN_USER
