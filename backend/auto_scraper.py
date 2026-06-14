"""Background auto-scrape scheduler."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from database import Database
from scraper import scrape_movies

MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 24 * 60
DEFAULT_INTERVAL_MINUTES = 60
DEFAULT_COUNT = 10
TICK_SECONDS = 30

_scrape_lock = asyncio.Lock()
_task: asyncio.Task | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class AutoScrapeService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get_settings(self) -> dict[str, Any]:
        enabled = self.db.get_meta("auto_scrape_enabled", "0") == "1"
        interval = int(self.db.get_meta("auto_scrape_interval_min", str(DEFAULT_INTERVAL_MINUTES)) or DEFAULT_INTERVAL_MINUTES)
        count = int(self.db.get_meta("auto_scrape_count", str(DEFAULT_COUNT)) or DEFAULT_COUNT)
        interval = max(MIN_INTERVAL_MINUTES, min(interval, MAX_INTERVAL_MINUTES))
        count = max(1, min(count, 50))
        return {
            "enabled": enabled,
            "interval_minutes": interval,
            "count": count,
            "last_run": self.db.get_meta("auto_scrape_last_run"),
            "next_run": self.db.get_meta("auto_scrape_next_run"),
            "last_result": self._last_result(),
            "running": _scrape_lock.locked(),
            "min_interval_minutes": MIN_INTERVAL_MINUTES,
        }

    def _last_result(self) -> dict[str, Any] | None:
        raw = self.db.get_meta("auto_scrape_last_result", "")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def save_settings(self, *, enabled: bool, interval_minutes: int, count: int) -> dict[str, Any]:
        interval_minutes = max(MIN_INTERVAL_MINUTES, min(int(interval_minutes), MAX_INTERVAL_MINUTES))
        count = max(1, min(int(count), 50))
        self.db.set_meta("auto_scrape_enabled", "1" if enabled else "0")
        self.db.set_meta("auto_scrape_interval_min", str(interval_minutes))
        self.db.set_meta("auto_scrape_count", str(count))

        if enabled:
            next_run = self.db.get_meta("auto_scrape_next_run")
            parsed = _parse_iso(next_run)
            if not parsed or parsed < _now():
                self.db.set_meta("auto_scrape_next_run", _now().isoformat())
        else:
            self.db.set_meta("auto_scrape_next_run", "")

        return self.get_settings()

    def _schedule_next(self, interval_minutes: int) -> None:
        self.db.set_meta(
            "auto_scrape_next_run",
            (_now() + timedelta(minutes=interval_minutes)).isoformat(),
        )

    async def run_once(self, count: int | None = None) -> dict[str, Any]:
        settings = self.get_settings()
        scrape_count = count if count is not None else settings["count"]
        async with _scrape_lock:
            result = await scrape_movies(scrape_count)
        self.db.set_meta("auto_scrape_last_run", _now().isoformat())
        self.db.set_meta(
            "auto_scrape_last_result",
            json.dumps({
                "saved": result.get("saved"),
                "skipped": result.get("skipped"),
                "skipped_duplicates": result.get("skipped_duplicates"),
                "total_in_db": result.get("total_in_db"),
                "error": None,
            }, ensure_ascii=False),
        )
        self._schedule_next(settings["interval_minutes"])
        return result

    async def tick(self) -> None:
        settings = self.get_settings()
        if not settings["enabled"]:
            return
        if _scrape_lock.locked():
            return

        next_run = _parse_iso(settings["next_run"])
        if next_run and _now() < next_run:
            return

        try:
            await self.run_once()
        except Exception as exc:
            self.db.set_meta("auto_scrape_last_run", _now().isoformat())
            self.db.set_meta(
                "auto_scrape_last_result",
                json.dumps({"saved": 0, "error": str(exc)}, ensure_ascii=False),
            )
            self._schedule_next(settings["interval_minutes"])


async def _loop(db: Database) -> None:
    service = AutoScrapeService(db)
    while True:
        try:
            await service.tick()
        except Exception:
            pass
        await asyncio.sleep(TICK_SECONDS)


def start_auto_scraper(db: Database) -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop(db))


async def stop_auto_scraper() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None


async def run_scrape_locked(count: int) -> dict[str, Any]:
    async with _scrape_lock:
        return await scrape_movies(count)
