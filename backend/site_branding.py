"""Site branding (logo, name, tagline) stored in SQLite meta."""

from __future__ import annotations

import os
import time
import re
from pathlib import Path
from typing import Any

from database import Database

PUBLIC_DIR = Path(os.environ.get("PUBLIC_DIR", "/app/public")).resolve()
UPLOADS_DIR = PUBLIC_DIR / "uploads"
DEFAULT_SITE_NAME = os.environ.get("SITE_NAME", "YTS")
DEFAULT_SITE_TAGLINE = os.environ.get("SITE_TAGLINE", "HD movies at the smallest file size")
MAX_LOGO_SIZE = 2 * 1024 * 1024
ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}
LOGO_BASENAME = "site-logo"


def _clean_text(value: str, *, max_len: int) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip())
    return text[:max_len]


def get_branding(db: Database | None = None) -> dict[str, Any]:
    database = db or Database()
    logo_url = database.get_meta("site_logo_url", "")
    logo_type = database.get_meta("site_logo_type", "text") or "text"
    if logo_type == "image" and not logo_url:
        logo_type = "text"
    return {
        "siteName": database.get_meta("site_name") or DEFAULT_SITE_NAME,
        "siteTagline": database.get_meta("site_tagline") or DEFAULT_SITE_TAGLINE,
        "logoUrl": logo_url,
        "logoType": logo_type,
    }


def save_branding(
    db: Database,
    *,
    site_name: str,
    site_tagline: str,
) -> dict[str, Any]:
    name = _clean_text(site_name, max_len=40) or DEFAULT_SITE_NAME
    tagline = _clean_text(site_tagline, max_len=120) or DEFAULT_SITE_TAGLINE
    db.set_meta("site_name", name)
    db.set_meta("site_tagline", tagline)
    return get_branding(db)


def _logo_path(ext: str) -> Path:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOADS_DIR / f"{LOGO_BASENAME}{ext.lower()}"


def _clear_logo_files() -> None:
    if not UPLOADS_DIR.is_dir():
        return
    for path in UPLOADS_DIR.glob(f"{LOGO_BASENAME}.*"):
        if path.is_file():
            path.unlink()


def save_logo(db: Database, filename: str, data: bytes) -> dict[str, Any]:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_LOGO_EXTENSIONS:
        raise ValueError("Logo must be PNG, JPG, WEBP, SVG, or GIF")
    if len(data) > MAX_LOGO_SIZE:
        raise ValueError("Logo too large (max 2 MB)")
    if ext == ".svg" and b"<script" in data.lower():
        raise ValueError("Invalid SVG file")

    _clear_logo_files()
    target = _logo_path(ext)
    target.write_bytes(data)
    db.set_meta("site_logo_url", f"/uploads/{target.name}?v={int(time.time())}")
    db.set_meta("site_logo_type", "image")
    return get_branding(db)


def remove_logo(db: Database) -> dict[str, Any]:
    _clear_logo_files()
    db.set_meta("site_logo_url", "")
    db.set_meta("site_logo_type", "text")
    return get_branding(db)
