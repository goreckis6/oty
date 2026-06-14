import asyncio
import os
from typing import Any

import httpx

from database import Database

YTS_BASE = os.environ.get("YTS_SCRAPE_URL", "https://yts.bz/api/v2").rstrip("/")


async def fetch_json(client: httpx.AsyncClient, path: str, **params: str) -> dict:
    res = await client.get(f"{YTS_BASE}/{path}", params=params, timeout=30.0)
    res.raise_for_status()
    data = res.json()
    if data.get("status") != "ok":
        raise RuntimeError(data.get("status_message", "YTS error"))
    return data["data"]


async def scrape_movies(count: int = 10) -> dict[str, Any]:
    count = max(1, min(int(count), 50))
    logs: list[str] = []

    async with httpx.AsyncClient(follow_redirects=True) as client:
        listing = await fetch_json(
            client,
            "list_movies.json",
            limit=str(count),
            sort_by="date_added",
            order_by="desc",
        )
        movies = listing.get("movies") or []
        detailed: list[dict] = []

        for m in movies[:count]:
            mid = m["id"]
            title = m.get("title", "?")
            logs.append(f"Scraping: {title} (id={mid})")
            detail = await fetch_json(
                client,
                "movie_details.json",
                movie_id=str(mid),
                with_images="true",
                with_cast="true",
            )
            detailed.append(detail["movie"])
            await asyncio.sleep(0.3)

        upcoming: list[dict] = []
        try:
            up_data = await fetch_json(client, "list_upcoming.json")
            upcoming = (up_data.get("movies") or [])[:8]
        except Exception as exc:
            logs.append(f"Upcoming skipped: {exc}")
            upcoming = movies[:4]

    db = Database()
    saved = db.upsert_movies(detailed)
    db.set_upcoming(upcoming)
    db.set_meta("last_scrape", __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat())
    db.set_meta("last_scrape_count", str(saved))

    return {
        "saved": saved,
        "source": YTS_BASE,
        "total_in_db": db.count_movies(),
        "logs": logs,
    }


def run_scrape(count: int = 10) -> dict[str, Any]:
    return asyncio.run(scrape_movies(count))
