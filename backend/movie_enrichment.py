"""Normalize trailers, screenshots and subtitle languages on movie records."""

from __future__ import annotations

import os
from typing import Any

# YIFY torrents typically bundle these subtitle languages (as on YTS).
YIFY_SUBTITLE_LANGS = (
    "us", "cz", "dk", "de", "gr", "es", "fi", "fr", "hu", "it", "nl", "no", "pl", "pt", "ro", "sv",
)

SUBTITLE_LABELS: dict[str, str] = {
    "us": "English",
    "cz": "Czech",
    "dk": "Danish",
    "de": "German",
    "gr": "Greek",
    "es": "Spanish",
    "fi": "Finnish",
    "fr": "French",
    "hu": "Hungarian",
    "it": "Italian",
    "nl": "Dutch",
    "no": "Norwegian",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "sv": "Swedish",
    # Common API aliases
    "en": "English",
    "el": "Greek",
}


def _screenshots(movie: dict[str, Any]) -> list[str]:
    shots: list[str] = []
    seen: set[str] = set()
    for i in range(1, 4):
        url = movie.get(f"large_screenshot_image{i}") or movie.get(f"medium_screenshot_image{i}")
        if url and url not in seen:
            seen.add(url)
            shots.append(url)
    return shots


def _trailer(movie: dict[str, Any]) -> dict[str, str]:
    code = (movie.get("yt_trailer_code") or "").strip()
    if not code:
        return {}
    return {
        "yt_trailer_code": code,
        "trailer_url": f"https://www.youtube.com/watch?v={code}",
        "trailer_embed": f"https://www.youtube.com/embed/{code}",
    }


def _normalize_subtitle_codes(raw: Any) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()

    def add(code: Any) -> None:
        if code is None:
            return
        key = str(code).strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        codes.append(key)

    if isinstance(raw, str):
        for part in raw.replace("|", ",").split(","):
            add(part.strip())
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                add(item.get("code") or item.get("lang") or item.get("language"))
            else:
                add(item)
    elif isinstance(raw, dict):
        for key, enabled in raw.items():
            if enabled:
                add(key)

    return codes


def _subtitles_from_movie(movie: dict[str, Any]) -> list[str]:
    for key in ("subtitles", "subtitle_langs", "subtitle_languages", "languages"):
        if key in movie and movie[key]:
            parsed = _normalize_subtitle_codes(movie[key])
            if parsed:
                return parsed

    for key, value in movie.items():
        if key.startswith("subtitle_") and value:
            add = key.removeprefix("subtitle_").lower()
            if add:
                return _normalize_subtitle_codes([add])

    for torrent in movie.get("torrents") or []:
        for key in ("subtitles", "subtitle_langs", "subtitle_languages"):
            if torrent.get(key):
                parsed = _normalize_subtitle_codes(torrent[key])
                if parsed:
                    return parsed

    if movie.get("torrents"):
        return list(YIFY_SUBTITLE_LANGS)
    return []


def subtitle_entries(codes: list[str]) -> list[dict[str, str]]:
    entries = []
    for code in codes:
        entries.append({
            "code": code,
            "label": SUBTITLE_LABELS.get(code, code.upper()),
        })
    return entries


def enrich_movie(movie: dict[str, Any]) -> dict[str, Any]:
    """Add normalized media fields used by the frontend."""
    enriched = dict(movie)
    enriched["screenshots"] = _screenshots(movie)
    enriched.update(_trailer(movie))

    codes = _subtitles_from_movie(movie)
    enriched["subtitle_langs"] = codes
    enriched["subtitles"] = subtitle_entries(codes)
    return enriched


async def fetch_opensubtitles_langs(
    client: Any,
    imdb_code: str,
) -> list[str] | None:
    """Optional: fetch real subtitle languages from OpenSubtitles when API key is set."""
    api_key = os.environ.get("OPENSUBTITLES_API_KEY", "").strip()
    if not api_key or not imdb_code:
        return None

    imdb_id = imdb_code.removeprefix("tt")
    try:
        res = await client.get(
            "https://api.opensubtitles.com/api/v1/subtitles",
            params={"imdb_id": imdb_id, "ai_translated": "exclude", "machine_translated": "exclude"},
            headers={"Api-Key": api_key, "User-Agent": "ytdown/1.0"},
            timeout=20.0,
        )
        if res.status_code != 200:
            return None
        data = res.json()
        langs: list[str] = []
        seen: set[str] = set()
        for item in data.get("data") or []:
            attrs = item.get("attributes") or {}
            lang = (attrs.get("language") or "").lower()
            if lang and lang not in seen:
                seen.add(lang)
                langs.append(lang)
        return langs or None
    except Exception:
        return None


async def enrich_movie_async(client: Any, movie: dict[str, Any]) -> dict[str, Any]:
    enriched = enrich_movie(movie)
    if movie.get("imdb_code"):
        os_langs = await fetch_opensubtitles_langs(client, movie["imdb_code"])
        if os_langs:
            mapped = []
            alias = {"en": "us", "el": "gr", "da": "dk", "cs": "cz", "nb": "no"}
            for lang in os_langs:
                mapped.append(alias.get(lang, lang))
            enriched["subtitle_langs"] = mapped
            enriched["subtitles"] = subtitle_entries(mapped)
            enriched["subtitles_source"] = "opensubtitles"
    return enriched
