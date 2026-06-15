"""Fetch .torrent files via fast mirrors with on-disk cache."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

HASH_RE = re.compile(r"^[a-f0-9]{40}$")
CACHE_DIR = Path(os.environ.get("TORRENT_CACHE_DIR", "/app/data/torrent_cache"))
MIRROR_TIMEOUT = float(os.environ.get("TORRENT_MIRROR_TIMEOUT", "5"))
YTS_HOSTS = [
    h.strip().rstrip("/")
    for h in os.environ.get(
        "YTS_TORRENT_HOSTS",
        "https://yts.lt,https://yts.mx,https://yts-official.mx",
    ).split(",")
    if h.strip()
]


def normalize_hash(value: str) -> str | None:
    h = (value or "").strip().lower()
    return h if HASH_RE.fullmatch(h) else None


def is_torrent_payload(data: bytes) -> bool:
    if len(data) < 32:
        return False
    return data[:1] == b"d" and b"4:info" in data[:512]


def cache_path(info_hash: str) -> Path:
    return CACHE_DIR / f"{info_hash}.torrent"


def _torrent_filename(fallback_url: str | None) -> str:
    if not fallback_url:
        return "movie.torrent"
    path = urlparse(fallback_url).path
    if "/" in path:
        name = path.rsplit("/", 1)[-1]
        if name.endswith(".torrent"):
            return name
    return "movie.torrent"


def source_urls(info_hash: str, fallback_url: str | None = None) -> list[str]:
    upper = info_hash.upper()
    filename = _torrent_filename(fallback_url)
    urls: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    for host in YTS_HOSTS:
        add(f"{host}/torrent/download/{upper}/{filename}")
    add(f"https://btcache.me/torrent/{upper}")
    add(f"https://torrage.info/torrent/{upper}.torrent")
    add(f"https://itorrents.org/torrent/{upper}.torrent")
    if fallback_url:
        add(fallback_url)
    return urls


class TorrentProxy:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._prefetch_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._client = httpx.AsyncClient(
            timeout=MIRROR_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; YTS/1.0)"},
        )

    async def close(self) -> None:
        for task in list(self._prefetch_tasks):
            task.cancel()
        if self._prefetch_tasks:
            await asyncio.gather(*self._prefetch_tasks, return_exceptions=True)
        self._prefetch_tasks.clear()
        if self._client:
            await self._client.aclose()
            self._client = None

    def is_cached(self, info_hash: str) -> bool:
        path = cache_path(info_hash)
        if not path.is_file():
            return False
        return is_torrent_payload(path.read_bytes())

    def write_cache(self, info_hash: str, data: bytes) -> None:
        if not is_torrent_payload(data):
            return
        cache_path(info_hash).write_bytes(data)

    async def _fetch_url(self, url: str) -> bytes | None:
        if not self._client:
            return None
        try:
            res = await self._client.get(url)
        except httpx.HTTPError:
            return None
        if res.status_code != 200:
            return None
        data = res.content
        return data if is_torrent_payload(data) else None

    async def fetch(self, info_hash: str, fallback_url: str | None = None) -> bytes | None:
        if self.is_cached(info_hash):
            return cache_path(info_hash).read_bytes()

        urls = source_urls(info_hash, fallback_url)
        tasks = [asyncio.create_task(self._fetch_url(url)) for url in urls]
        try:
            for task in asyncio.as_completed(tasks):
                data = await task
                if data:
                    self.write_cache(info_hash, data)
                    return data
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return None

    def _track_prefetch(self, task: asyncio.Task[None]) -> None:
        self._prefetch_tasks.add(task)
        task.add_done_callback(self._prefetch_tasks.discard)

    def prefetch(self, info_hash: str, fallback_url: str | None = None) -> None:
        if self.is_cached(info_hash):
            return

        async def _run() -> None:
            await self.fetch(info_hash, fallback_url)

        task = asyncio.create_task(_run())
        self._track_prefetch(task)

    def prefetch_movie(self, movie: dict) -> None:
        for torrent in movie.get("torrents") or []:
            info_hash = normalize_hash(str(torrent.get("hash") or ""))
            if info_hash:
                self.prefetch(info_hash, torrent.get("url"))
