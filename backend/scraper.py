import asyncio
import os
from typing import Any

import httpx

from database import Database, normalize_title
from movie_enrichment import enrich_movie_async, merge_listing_movie
from seo import register_movies_for_seo

YTS_BASE = os.environ.get("YTS_SCRAPE_URL", "https://yts.bz/api/v2").rstrip("/")
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")
PAGE_SIZE = 50
MAX_LISTING_MOVIES = 3000
MAX_PAGES = (MAX_LISTING_MOVIES + PAGE_SIZE - 1) // PAGE_SIZE


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
    count = max(1, int(count))
    logs: list[str] = []
    db = Database()
    known_ids = db.existing_ids()
    known_titles = db.existing_titles()
    detailed: list[dict] = []
    skipped = 0
    skipped_duplicates = 0

    async with httpx.AsyncClient(follow_redirects=True) as client:
        page = 1
        while len(detailed) < count and page <= MAX_PAGES:
            listing = await fetch_json(
                client,
                "list_movies.json",
                limit=str(PAGE_SIZE),
                page=str(page),
                sort_by="date_added",
                order_by="desc",
            )
            assert listing is not None
            movies = listing.get("movies") or []
            if not movies:
                logs.append(f"Koniec listy YTS (strona {page}).")
                break

            for m in movies:
                mid = int(m["id"])
                title = m.get("title", "?")
                if mid in known_ids:
                    skipped += 1
                    continue

                title_key = normalize_title(title)
                if title_key and title_key in known_titles:
                    skipped_duplicates += 1
                    logs.append(f"Pominięto duplikat tytułu: {title} (id={mid})")
                    continue

                logs.append(f"Dodaję: {title} (id={mid})")
                detail = await fetch_json(
                    client,
                    "movie_details.json",
                    movie_id=str(mid),
                    with_images="true",
                    with_cast="true",
                )
                assert detail is not None
                movie = merge_listing_movie(m, detail["movie"])
                movie = await enrich_movie_async(client, movie)
                detailed.append(movie)
                known_ids.add(mid)
                movie_title = normalize_title(movie.get("title") or title)
                if movie_title:
                    known_titles.add(movie_title)
                if len(detailed) >= count:
                    break
                await asyncio.sleep(0.3)

            if len(detailed) >= count:
                break
            page += 1
            await asyncio.sleep(0.2)

        if skipped:
            logs.append(f"Pominięto {skipped} filmów już w bazie (po ID).")
        if skipped_duplicates:
            logs.append(f"Pominięto {skipped_duplicates} filmów z powtarzającym się tytułem.")

        if not detailed:
            logs.append("Brak nowych filmów do dodania.")
        elif len(detailed) < count:
            logs.append(f"Dodano {len(detailed)} z żądanych {count} (więcej nie ma na YTS).")

        upcoming, upcoming_note = await fetch_upcoming(client, detailed)
        if upcoming_note:
            logs.append(upcoming_note)

    saved = db.upsert_movies(detailed)
    batch_ids = [int(m["id"]) for m in detailed]
    db.set_last_batch_ids(batch_ids)
    db.set_upcoming(upcoming)
    db.set_meta("last_scrape", __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat())
    db.set_meta("last_scrape_count", str(saved))

    seo_urls = register_movies_for_seo(db, detailed)
    if seo_urls:
        logs.append(f"SEO: {len(seo_urls)} nowych stron gotowych (meta + sitemap automatycznie).")
        for url in seo_urls:
            logs.append(f"  → {url}")
    elif saved == 0:
        logs.append("SEO: brak nowych stron (sitemap bez zmian).")

    return {
        "saved": saved,
        "skipped": skipped,
        "skipped_duplicates": skipped_duplicates,
        "seo_urls": seo_urls,
        "sitemap_url": f"{SITE_URL}/sitemap.xml" if SITE_URL else "/sitemap.xml",
        "source": YTS_BASE,
        "total_in_db": db.count_movies(),
        "logs": logs,
    }


def run_scrape(count: int = 10) -> dict[str, Any]:
    return asyncio.run(scrape_movies(count))
