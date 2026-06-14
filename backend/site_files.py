"""Manage public site root files (verification HTML/XML, etc.)."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PUBLIC_DIR = Path(os.environ.get("PUBLIC_DIR", "/app/public")).resolve()
MAX_FILE_SIZE = 256 * 1024
ALLOWED_EXTENSIONS = {".html", ".htm", ".txt", ".xml", ".json"}
PROTECTED_NAMES = {"index.html"}
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _allowed_extension(name: str) -> bool:
    return Path(name).suffix.lower() in ALLOWED_EXTENSIONS


def _is_safe_name(name: str) -> bool:
    return bool(name and SAFE_NAME_RE.match(name) and _allowed_extension(name))


def resolve_site_path(rel_path: str) -> Path:
    rel = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        raise ValueError("Invalid path")

    parts = [p for p in rel.split("/") if p]
    if len(parts) == 1:
        name = parts[0]
        if not _is_safe_name(name):
            raise ValueError("Invalid file name")
        return PUBLIC_DIR / name

    if len(parts) == 2 and parts[0] == ".well-known" and _is_safe_name(parts[1]):
        target = PUBLIC_DIR / ".well-known" / parts[1]
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    raise ValueError("Only site root files or .well-known/ files are allowed")


def is_protected(rel_path: str) -> bool:
    name = rel_path.split("/")[-1]
    return name in PROTECTED_NAMES


def _file_info(path: Path, rel_path: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": rel_path,
        "name": path.name,
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "url": f"/{rel_path}",
        "protected": is_protected(rel_path),
        "editable": path.suffix.lower() in {".html", ".htm", ".txt", ".xml", ".json"},
    }


def list_site_files() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not PUBLIC_DIR.is_dir():
        return items

    for entry in sorted(PUBLIC_DIR.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_file() and _allowed_extension(entry.name):
            items.append(_file_info(entry, entry.name))

    well_known = PUBLIC_DIR / ".well-known"
    if well_known.is_dir():
        for entry in sorted(well_known.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_file() and _allowed_extension(entry.name):
                items.append(_file_info(entry, f".well-known/{entry.name}"))

    return items


def read_site_file(rel_path: str) -> dict[str, Any]:
    path = resolve_site_path(rel_path)
    if not path.is_file():
        raise FileNotFoundError("File not found")
    data = path.read_bytes()
    if len(data) > MAX_FILE_SIZE:
        raise ValueError("File too large")
    try:
        content = data.decode("utf-8")
        binary = False
    except UnicodeDecodeError:
        content = ""
        binary = True
    return {**_file_info(path, rel_path), "content": content, "binary": binary}


def write_site_file(rel_path: str, content: str, *, overwrite: bool = True) -> dict[str, Any]:
    if is_protected(rel_path):
        raise ValueError("Protected file")
    path = resolve_site_path(rel_path)
    if path.exists() and not overwrite:
        raise ValueError("File already exists")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_FILE_SIZE:
        raise ValueError("File too large")
    path.write_bytes(encoded)
    return _file_info(path, rel_path)


def upload_site_file(rel_path: str, data: bytes, *, overwrite: bool = True) -> dict[str, Any]:
    if is_protected(rel_path):
        raise ValueError("Protected file")
    if len(data) > MAX_FILE_SIZE:
        raise ValueError("File too large")
    path = resolve_site_path(rel_path)
    if path.exists() and not overwrite:
        raise ValueError("File already exists")
    path.write_bytes(data)
    return _file_info(path, rel_path)


def delete_site_file(rel_path: str) -> None:
    if is_protected(rel_path):
        raise ValueError("Protected file")
    path = resolve_site_path(rel_path)
    if not path.is_file():
        raise FileNotFoundError("File not found")
    path.unlink()
