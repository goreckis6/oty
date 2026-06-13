#!/usr/bin/env python3
"""Konwertuje cookies.json (Chrome / EditThisCookie) → cookies.txt (Netscape dla yt-dlp)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HEADER = """# Netscape HTTP Cookie File
# https://curl.haxx.se/rfc/cookie_spec.html
# This is a generated file! Do not edit.

"""

YOUTUBE_DOMAIN = re.compile(
    r"(^|\.)youtube\.com$|(^|\.)google\.com$|^accounts\.google\.com$",
    re.IGNORECASE,
)


def _domain_flag(cookie: dict) -> tuple[str, str]:
    domain = cookie.get("domain", "")
    host_only = cookie.get("hostOnly", False)
    if host_only:
        return domain, "FALSE"
    if not domain.startswith("."):
        domain = f".{domain.lstrip('.')}"
    return domain, "TRUE"


def _expiration(cookie: dict) -> str:
    if cookie.get("session"):
        return "0"
    exp = cookie.get("expirationDate")
    if exp is None:
        return "0"
    return str(int(exp))


def convert(items: list[dict], youtube_only: bool = True) -> str:
    rows: dict[tuple[str, str], str] = {}
    for cookie in items:
        if not isinstance(cookie, dict):
            continue
        domain = cookie.get("domain", "")
        name = cookie.get("name", "")
        value = cookie.get("value", "")
        if not domain or not name:
            continue
        if youtube_only and not YOUTUBE_DOMAIN.search(domain):
            continue
        domain, include_subdomains = _domain_flag(cookie)
        path = cookie.get("path") or "/"
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        line = "\t".join(
            [domain, include_subdomains, path, secure, _expiration(cookie), name, value]
        )
        rows[(domain, name)] = line
    return HEADER + "\n".join(rows.values()) + ("\n" if rows else "")


def main() -> int:
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} cookies.json cookies.txt", file=sys.stderr)
        return 1
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    if not src.is_file():
        print(f"Brak pliku: {src}", file=sys.stderr)
        return 1
    data = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("cookies.json musi być tablicą obiektów", file=sys.stderr)
        return 1
    out = convert(data)
    dst.write_text(out, encoding="utf-8")
    count = max(0, out.count("\n") - 4)
    print(f"==> cookies.txt: {count} wpisów YouTube/Google z {src}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
