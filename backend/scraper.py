import asyncio
import os
from typing import Any

import httpx

from database import Database, normalize_title
from movie_enrichment import enrich_movie_async, merge_listing_movie
from movie_store import MovieStore
from seo import register_movies_for_seo

YTS_BASE = os.environ.get("YTS_SCRAPE_URL", "https://yts.bz/api/v2").rstrip("/")
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")
PAGE_SIZE = 50
MAX_LISTING_MOVIES = 80_000
MAX_PAGES = (MAX_LISTING_MOVIES + PAGE_SIZE - 1) // PAGE_SIZE
PAGES_PER_RUN = int(os.environ.get("SCRAPE_MAX_PAGES", "50"))
PAGES_PER_RUN_MANUAL = int(os.environ.get("SCRAPE_MAX_PAGES_MANUAL", "500"))
FULL_SKIP_STOP_PAGES = int(os.environ.get("SCRAPE_FULL_SKIP_STOP", "3"))
SCRAPE_RESUME_PAGE_KEY = "scrape_resume_page"


def _get_resume_page(db: Database) -> int:
    try:
        return max(1, min(int(db.get_meta(SCRAPE_RESUME_PAGE_KEY, "1") or 1), MAX_PAGES))
    except ValueError:
        return 1


def _set_resume_page(db: Database, page: int) -> None:
    db.set_meta(SCRAPE_RESUME_PAGE_KEY, str(max(1, min(page, MAX_PAGES))))


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


async def scrape_movies(count: int = 10, *, background: bool = False) -> dict[str, Any]:
    count = max(1, int(count))
    logs: list[str] = []
    db = Database()
    known_ids = db.existing_ids()
    known_titles = db.existing_titles()
    detailed: list[dict] = []
    skipped = 0
    skipped_duplicates = 0
    pages_scanned = 0
    consecutive_full_skip_pages = 0
    start_page = _get_resume_page(db)
    page = start_page
    page_limit = PAGES_PER_RUN if background else PAGES_PER_RUN_MANUAL
    catalog_end = False

    if start_page > 1:
        logs.append(f"Kontynuacja od strony {start_page} (katalog YTS, sort. date_added).")

    async with httpx.AsyncClient(follow_redirects=True) as client:
        while len(detailed) < count and page <= MAX_PAGES:
            pages_scanned += 1
            if pages_scanned > page_limit:
                if background:
                    logs.append(
                        f"Auto: przeskanowano {page_limit} stron od str. {start_page}, "
                        f"pominięto {skipped} — kontynuacja od str. {page}."
                    )
                else:
                    logs.append(
                        f"Limit skanowania: {page_limit} stron w tym uruchomieniu "
                        f"(kontynuacja od str. {page} przy następnym kliknięciu)."
                    )
                break
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
                catalog_end = True
                if not background:
                    logs.append(f"Koniec listy YTS (strona {page}).")
                break

            page_had_new = False
            for m in movies:
                mid = int(m["id"])
                title = m.get("title", "?")
                if mid in known_ids:
                    skipped += 1
                    continue

                title_key = normalize_title(title)
                if title_key and title_key in known_titles:
                    skipped_duplicates += 1
                    if not background:
                        logs.append(f"Pominięto duplikat tytułu: {title} (id={mid})")
                    continue

                page_had_new = True
                if not background:
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
                await asyncio.sleep(0.1 if background else 0.3)

            if background and not page_had_new:
                consecutive_full_skip_pages += 1
                if (
                    start_page == 1
                    and consecutive_full_skip_pages >= FULL_SKIP_STOP_PAGES
                    and not detailed
                ):
                    next_page = page + 1
                    _set_resume_page(db, next_page)
                    logs.append(
                        f"Auto: najnowsze filmy już w bazie — następne skanowanie od strony {next_page}."
                    )
                    break
            else:
                consecutive_full_skip_pages = 0

            if len(detailed) >= count:
                break
            page += 1
            await asyncio.sleep(0.1 if background else 0.2)

        if skipped and not background:
            logs.append(f"Pominięto {skipped} filmów już w bazie (po ID).")
        elif skipped and background and not any("pominięto" in line for line in logs):
            logs.append(f"Auto: pominięto {skipped} filmów już w bazie (w tle).")

        if skipped_duplicates and not background:
            logs.append(f"Pominięto {skipped_duplicates} filmów z powtarzającym się tytułem.")

        if not detailed:
            if not background:
                logs.append("Brak nowych filmów do dodania w tym zakresie stron.")
        elif len(detailed) < count and not background:
            logs.append(f"Dodano {len(detailed)} z żądanych {count} (więcej nie ma na YTS).")
        elif background and detailed:
            logs.append(f"Auto: dodano {len(detailed)} nowych filmów.")

        upcoming, upcoming_note = await fetch_upcoming(client, detailed)
        if upcoming_note and not background:
            logs.append(upcoming_note)

    if catalog_end:
        _set_resume_page(db, 1)
        logs.append("Koniec katalogu YTS — następne skanowanie od strony 1.")
    else:
        _set_resume_page(db, page)
        if not any("następne skanowanie" in line.lower() for line in logs):
            logs.append(f"Następne skanowanie: strona {page}.")

    saved = db.upsert_movies(detailed)
    batch_ids = [int(m["id"]) for m in detailed]
    db.set_last_batch_ids(batch_ids)
    known_ids = db.existing_ids()
    upcoming = [m for m in upcoming if int(m.get("id") or 0) in known_ids]
    db.set_upcoming(upcoming)
    db.set_meta("last_scrape", __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat())
    db.set_meta("last_scrape_count", str(saved))
    if saved:
        MovieStore.invalidate_dup_cache()

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
        "pages_scanned": pages_scanned,
        "resume_page": _get_resume_page(db),
        "start_page": start_page,
        "seo_urls": seo_urls,
        "sitemap_url": f"{SITE_URL}/sitemap.xml" if SITE_URL else "/sitemap.xml",
        "source": YTS_BASE,
        "total_in_db": db.count_movies(),
        "logs": logs,
        "background": background,
    }


def run_scrape(count: int = 10) -> dict[str, Any]:
    return asyncio.run(scrape_movies(count))
