#!/usr/bin/env python3
"""Pobiera 10 filmów z yts.bz i zapisuje do backend/data/test_movies.json."""

import asyncio
import json
from pathlib import Path

import httpx

YTS_BASE = "https://yts.bz/api/v2"
OUT = Path(__file__).resolve().parent / "data" / "test_movies.json"
COUNT = 10


async def fetch_json(client: httpx.AsyncClient, path: str, **params: str) -> dict:
    res = await client.get(f"{YTS_BASE}/{path}", params=params, timeout=30.0)
    res.raise_for_status()
    data = res.json()
    if data.get("status") != "ok":
        raise RuntimeError(data.get("status_message", "YTS error"))
    return data["data"]


async def scrape() -> dict:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        listing = await fetch_json(
            client,
            "list_movies.json",
            limit=str(COUNT),
            sort_by="date_added",
            order_by="desc",
        )
        movies = listing.get("movies") or []
        detailed: list[dict] = []

        for m in movies[:COUNT]:
            mid = m["id"]
            print(f"  → {m.get('title')} ({m.get('year')}) id={mid}")
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
            print(f"  (upcoming skipped: {exc})")
            upcoming = movies[:4]

        return {
            "source": YTS_BASE,
            "count": len(detailed),
            "movies": detailed,
            "upcoming": upcoming,
        }


def main() -> None:
    print(f"Scraping {COUNT} movies from {YTS_BASE}...")
    payload = asyncio.run(scrape())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {payload['count']} movies → {OUT}")


if __name__ == "__main__":
    main()
