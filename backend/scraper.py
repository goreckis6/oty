import asyncio
import json
import os
from datetime import datetime, timezone
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
SCRAPE_LAST_SCAN_KEY = "scrape_last_scan"


def _get_resume_page(db: Database) -> int:
    try:
        return max(1, min(int(db.get_meta(SCRAPE_RESUME_PAGE_KEY, "1") or 1), MAX_PAGES))
    except ValueError:
        return 1


def _set_resume_page(db: Database, page: int) -> None:
    db.set_meta(SCRAPE_RESUME_PAGE_KEY, str(max(1, min(page, MAX_PAGES))))


def _save_last_scan(
    db: Database,
    *,
    background: bool,
    start_page: int,
    scan: dict[str, Any],
    saved: int,
) -> None:
    db.set_meta(
        SCRAPE_LAST_SCAN_KEY,
        json.dumps(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "mode": "auto" if background else "manual",
                "start_page": start_page,
                "pages_scanned": scan["pages_scanned"],
                "skipped": scan["skipped"],
                "skipped_duplicates": scan["skipped_duplicates"],
                "candidates_found": len(scan["candidates"]),
                "saved": saved,
                "resume_page": _get_resume_page(db),
            },
            ensure_ascii=False,
        ),
    )


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


async def _scan_listing_candidates(
    client: httpx.AsyncClient,
    *,
    start_page: int,
    page_limit: int,
    need_count: int,
    known_ids: set[int],
    known_titles: set[str],
    background: bool,
) -> dict[str, Any]:
    """Phase 1: list-only scan — find movies missing from DB without detail API calls."""
    candidates: list[dict[str, Any]] = []
    skipped = 0
    skipped_duplicates = 0
    pages_scanned = 0
    page = start_page
    catalog_end = False
    hit_page_limit = False
    consecutive_full_skip_pages = 0
    early_stop = False

    while len(candidates) < need_count and page <= MAX_PAGES:
        pages_scanned += 1
        if pages_scanned > page_limit:
            hit_page_limit = True
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
            break

        page_had_new = False
        for m in movies:
            mid = int(m["id"])
            if mid in known_ids:
                skipped += 1
                continue

            title_key = normalize_title(m.get("title"))
            if title_key and title_key in known_titles:
                skipped_duplicates += 1
                continue

            page_had_new = True
            candidates.append(m)
            if len(candidates) >= need_count:
                break

        if background and not page_had_new:
            consecutive_full_skip_pages += 1
            if (
                start_page == 1
                and consecutive_full_skip_pages >= FULL_SKIP_STOP_PAGES
                and not candidates
            ):
                early_stop = True
                break
        else:
            consecutive_full_skip_pages = 0

        if len(candidates) >= need_count:
            break

        page += 1
        if background or page_had_new:
            await asyncio.sleep(0.05 if not background else 0.1)

    return {
        "candidates": candidates,
        "skipped": skipped,
        "skipped_duplicates": skipped_duplicates,
        "pages_scanned": pages_scanned,
        "next_page": page,
        "catalog_end": catalog_end,
        "hit_page_limit": hit_page_limit,
        "early_stop": early_stop,
    }


def _log_scan_summary(
    logs: list[str],
    *,
    background: bool,
    start_page: int,
    scan: dict[str, Any],
) -> None:
    candidates = scan["candidates"]
    pages = scan["pages_scanned"]
    skipped = scan["skipped"]
    skipped_dup = scan["skipped_duplicates"]

    if background:
        logs.append(
            f"Auto: skan list ({pages} str. od {start_page}): "
            f"{len(candidates)} nowych, {skipped} w bazie, {skipped_dup} dupl. tytułu."
        )
        return

    logs.append(
        f"Szybkie skanowanie list YTS (str. {start_page}, {pages} str.): "
        f"w bazie {skipped}, duplikatów tytułu {skipped_dup}."
    )
    if candidates:
        logs.append(f"Do pobrania: {len(candidates)} filmów:")
        for m in candidates[:12]:
            logs.append(f"  → {m.get('title', '?')} (id={m.get('id')})")
        if len(candidates) > 12:
            logs.append(f"  … i {len(candidates) - 12} więcej")
        logs.append("Pobieranie szczegółów z YTS…")
    else:
        logs.append("W tym zakresie brak nowych filmów — nic do pobrania.")


async def _fetch_candidate_details(
    client: httpx.AsyncClient,
    candidates: list[dict[str, Any]],
    *,
    known_ids: set[int],
    known_titles: set[str],
    background: bool,
    logs: list[str],
) -> list[dict[str, Any]]:
    """Phase 2: full movie_details only for candidates from phase 1."""
    detailed: list[dict[str, Any]] = []
    for m in candidates:
        mid = int(m["id"])
        title = m.get("title", "?")
        if not background:
            logs.append(f"Pobieram: {title} (id={mid})")
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
        await asyncio.sleep(0.1 if background else 0.25)
    return detailed


async def scrape_movies(count: int = 10, *, background: bool = False) -> dict[str, Any]:
    count = max(1, int(count))
    logs: list[str] = []
    db = Database()
    known_ids = db.existing_ids()
    known_titles = db.existing_titles()
    start_page = _get_resume_page(db)
    page_limit = PAGES_PER_RUN if background else PAGES_PER_RUN_MANUAL

    if start_page > 1 and not background:
        logs.append(f"Kontynuacja od strony {start_page} (katalog YTS, sort. date_added).")

    async with httpx.AsyncClient(follow_redirects=True) as client:
        scan = await _scan_listing_candidates(
            client,
            start_page=start_page,
            page_limit=page_limit,
            need_count=count,
            known_ids=known_ids,
            known_titles=known_titles,
            background=background,
        )
        _log_scan_summary(logs, background=background, start_page=start_page, scan=scan)

        detailed = await _fetch_candidate_details(
            client,
            scan["candidates"],
            known_ids=known_ids,
            known_titles=known_titles,
            background=background,
            logs=logs,
        )

        if scan["skipped"] and background and not any("w bazie" in line for line in logs):
            logs.append(f"Auto: pominięto {scan['skipped']} filmów już w bazie (w tle).")
        elif scan["skipped"] and not background and not detailed:
            logs.append(f"Pominięto {scan['skipped']} filmów już w bazie (po ID).")
        if scan["skipped_duplicates"] and not background and not detailed:
            logs.append(f"Pominięto {scan['skipped_duplicates']} filmów z powtarzającym się tytułem.")

        if not detailed:
            if not background:
                logs.append("Brak nowych filmów do dodania w tym zakresie stron.")
        elif len(detailed) < count and not background:
            logs.append(f"Dodano {len(detailed)} z żądanych {count} (więcej nie ma na YTS).")
        elif background and detailed:
            logs.append(f"Auto: dodano {len(detailed)} nowych filmów.")

        if scan["hit_page_limit"]:
            if background:
                logs.append(
                    f"Auto: przeskanowano {page_limit} stron od str. {start_page} — "
                    f"kontynuacja od str. {scan['next_page']}."
                )
            else:
                logs.append(
                    f"Limit skanowania: {page_limit} stron w tym uruchomieniu "
                    f"(kontynuacja od str. {scan['next_page']} przy następnym kliknięciu)."
                )
        elif scan["early_stop"]:
            next_page = scan["next_page"] + 1
            _set_resume_page(db, next_page)
            logs.append(
                f"Auto: najnowsze filmy już w bazie — następne skanowanie od strony {next_page}."
            )
        elif scan["catalog_end"] and not background:
            logs.append(f"Koniec listy YTS (strona {scan['next_page']}).")

        upcoming, upcoming_note = await fetch_upcoming(client, detailed)
        if upcoming_note and not background:
            logs.append(upcoming_note)

    if scan["catalog_end"]:
        _set_resume_page(db, 1)
        logs.append("Koniec katalogu YTS — następne skanowanie od strony 1.")
    elif not scan["early_stop"]:
        _set_resume_page(db, scan["next_page"])
        if not any("następne skanowanie" in line.lower() for line in logs):
            logs.append(f"Następne skanowanie: strona {scan['next_page']}.")

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

    _save_last_scan(db, background=background, start_page=start_page, scan=scan, saved=saved)

    return {
        "saved": saved,
        "skipped": scan["skipped"],
        "skipped_duplicates": scan["skipped_duplicates"],
        "candidates_found": len(scan["candidates"]),
        "pages_scanned": scan["pages_scanned"],
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
