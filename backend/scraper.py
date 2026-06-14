import asyncio
import os
from typing import Any

import httpx

from database import Database

YTS_BASE = os.environ.get("YTS_SCRAPE_URL", "https://yts.bz/api/v2").rstrip("/")


async def fetch_json(
    client: httpx.AsyncClient, path: str, *, allow_404: bool = False, **params: str
) -> dict | None:
    res = await client.get(f"{YTS_BASE}/{path}", params=params, timeout=30.0)
    if allow_404 and res.status_code == 404:
        return None
    res.raise_for_status()
    data = res.json()
    if data.get("status") != "ok":
        raise RuntimeError(data.get("status_message", "YTS error"))
    return data["data"]


async def fetch_upcoming(client: httpx.AsyncClient, fallback: list[dict]) -> tuple[list[dict], str | None]:
    """yts.bz often has no list_upcoming — use alternate list or fallback."""
    data = await fetch_json(client, "list_upcoming.json", allow_404=True)
    if data and data.get("movies"):
        return (data["movies"])[:8], None

    # Newer / higher year titles as "upcoming" substitute
    alt = await fetch_json(
        client,
        "list_movies.json",
        limit="8",
        sort_by="year",
        order_by="desc",
    )
    if alt and alt.get("movies"):
        return alt["movies"][:8], "Upcoming: użyto listy po roku (API upcoming niedostępne)"

    return fallback[:4], "Upcoming: użyto najnowszych z bieżącego scrapingu"


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
        assert listing is not None
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
            assert detail is not None
            detailed.append(detail["movie"])
            await asyncio.sleep(0.3)

        upcoming, upcoming_note = await fetch_upcoming(client, movies)
        if upcoming_note:
            logs.append(upcoming_note)

    db = Database()
    saved = db.upsert_movies(detailed)
    batch_ids = [int(m["id"]) for m in detailed]
    db.set_last_batch_ids(batch_ids)
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
