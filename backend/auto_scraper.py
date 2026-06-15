"""Background auto-scrape scheduler."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from database import Database
from scraper import SCRAPE_LAST_SCAN_KEY, download_pending_movies, scrape_state, scrape_movies, scan_listings_only

logger = logging.getLogger(__name__)

MIN_INTERVAL_MINUTES = 2
MAX_INTERVAL_MINUTES = 24 * 60
DEFAULT_INTERVAL_MINUTES = 60
DEFAULT_COUNT = 10
TICK_SECONDS = 30

_scrape_lock = asyncio.Lock()
_task: asyncio.Task | None = None
_db: Database | None = None


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

    def _last_scan(self) -> dict[str, Any] | None:
        raw = self.db.get_meta(SCRAPE_LAST_SCAN_KEY, "")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def get_settings(self) -> dict[str, Any]:
        enabled = self.db.get_meta("auto_scrape_enabled", "0") == "1"
        interval = int(self.db.get_meta("auto_scrape_interval_min", str(DEFAULT_INTERVAL_MINUTES)) or DEFAULT_INTERVAL_MINUTES)
        count = int(self.db.get_meta("auto_scrape_count", str(DEFAULT_COUNT)) or DEFAULT_COUNT)
        interval = max(MIN_INTERVAL_MINUTES, min(interval, MAX_INTERVAL_MINUTES))
        count = max(1, count)
        next_run = self.db.get_meta("auto_scrape_next_run")
        next_dt = _parse_iso(next_run)
        now = _now()
        return {
            "enabled": enabled,
            "interval_minutes": interval,
            "count": count,
            "last_run": self.db.get_meta("auto_scrape_last_run"),
            "next_run": next_run,
            "next_run_overdue": bool(enabled and next_dt and now >= next_dt),
            "last_result": self._last_result(),
            "running": _scrape_lock.locked(),
            "scheduler_alive": _task is not None and not _task.done(),
            "min_interval_minutes": MIN_INTERVAL_MINUTES,
            "scrape_resume_page": int(self.db.get_meta("scrape_resume_page", "1") or 1),
            "movies_in_db": self.db.count_movies(),
            "scrape_last_scan": self._last_scan(),
            "scrape_queue": scrape_state(self.db),
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
        count = max(1, int(count))
        self.db.set_meta("auto_scrape_enabled", "1" if enabled else "0")
        self.db.set_meta("auto_scrape_interval_min", str(interval_minutes))
        self.db.set_meta("auto_scrape_count", str(count))

        if enabled:
            next_run = self.db.get_meta("auto_scrape_next_run")
            parsed = _parse_iso(next_run)
            if not parsed or parsed <= _now():
                self.db.set_meta("auto_scrape_next_run", _now().isoformat())
        else:
            self.db.set_meta("auto_scrape_next_run", "")

        settings = self.get_settings()
        if enabled:
            trigger_auto_scrape_tick()
        return settings

    def _schedule_next(self, interval_minutes: int) -> None:
        self.db.set_meta(
            "auto_scrape_next_run",
            (_now() + timedelta(minutes=interval_minutes)).isoformat(),
        )

    async def run_once(self, count: int | None = None) -> dict[str, Any]:
        settings = self.get_settings()
        scrape_count = count if count is not None else settings["count"]
        async with _scrape_lock:
            result = await scrape_movies(scrape_count, background=True)
        self.db.set_meta("auto_scrape_last_run", _now().isoformat())
        self.db.set_meta(
            "auto_scrape_last_result",
            json.dumps({
                "saved": result.get("saved"),
                "skipped": result.get("skipped"),
                "skipped_duplicates": result.get("skipped_duplicates"),
                "candidates_found": result.get("candidates_found"),
                "pages_scanned": result.get("pages_scanned"),
                "start_page": result.get("start_page"),
                "resume_page": result.get("resume_page"),
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
            logger.exception("auto-scrape failed")
            self.db.set_meta("auto_scrape_last_run", _now().isoformat())
            self.db.set_meta(
                "auto_scrape_last_result",
                json.dumps({"saved": 0, "error": str(exc)}, ensure_ascii=False),
            )
            self._schedule_next(settings["interval_minutes"])


async def _loop(db: Database) -> None:
    service = AutoScrapeService(db)
    logger.info("auto-scrape scheduler started")
    while True:
        try:
            await service.tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("auto-scrape tick failed")
        await asyncio.sleep(TICK_SECONDS)


def _restart_loop_if_needed() -> None:
    global _task, _db
    if _db is None:
        return
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop(_db), name="auto-scrape-loop")
    _task.add_done_callback(_on_loop_done)


def _on_loop_done(task: asyncio.Task) -> None:
    global _task
    _task = None
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error("auto-scrape loop stopped: %s", exc)
    _restart_loop_if_needed()


def trigger_auto_scrape_tick() -> None:
    if _db is None:
        return
    asyncio.create_task(AutoScrapeService(_db).tick(), name="auto-scrape-tick")


def start_auto_scraper(db: Database) -> None:
    global _db
    _db = db
    _restart_loop_if_needed()
    trigger_auto_scrape_tick()


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


async def run_scan_locked(count: int) -> dict[str, Any]:
    async with _scrape_lock:
        return await scan_listings_only(count)


async def run_download_locked(count: int) -> dict[str, Any]:
    async with _scrape_lock:
        return await download_pending_movies(count)
