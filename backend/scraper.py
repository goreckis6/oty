import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from database import Database, normalize_title
from movie_enrichment import enrich_movie_async, merge_listing_movie
from movie_store import MovieStore
from seo import register_movies_for_seo

logger = logging.getLogger(__name__)


def _yts_mirror_urls() -> list[str]:
    primary = os.environ.get("YTS_SCRAPE_URL", "https://yts.bz/api/v2").strip().rstrip("/")
    extra_raw = os.environ.get(
        "YTS_SCRAPE_MIRROR_URLS",
        "https://yts.bz/api/v2,https://yts.gg/api/v2",
    )
    urls: list[str] = []
    for u in [primary, *extra_raw.split(",")]:
        u = u.strip().rstrip("/")
        if u and u not in urls:
            urls.append(u)
    return urls or ["https://yts.bz/api/v2"]


YTS_MIRROR_URLS = _yts_mirror_urls()
YTS_BASE = YTS_MIRROR_URLS[0]
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")
PAGE_SIZE = 50
MAX_LISTING_MOVIES = 80_000
MAX_PAGES = (MAX_LISTING_MOVIES + PAGE_SIZE - 1) // PAGE_SIZE
PAGES_PER_RUN = int(os.environ.get("SCRAPE_MAX_PAGES", "50"))
PAGES_PER_RUN_MANUAL = int(os.environ.get("SCRAPE_MAX_PAGES_MANUAL", "500"))
FULL_SKIP_STOP_PAGES = int(os.environ.get("SCRAPE_FULL_SKIP_STOP", "3"))
PARALLEL_LIST_PAGES = int(os.environ.get("SCRAPE_PARALLEL_PAGES", "8"))
LISTING_TIMEOUT = float(os.environ.get("SCRAPE_LISTING_TIMEOUT", "12"))
DETAIL_TIMEOUT = float(os.environ.get("SCRAPE_DETAIL_TIMEOUT", "60"))
DETAIL_RETRIES = max(1, int(os.environ.get("SCRAPE_DETAIL_RETRIES", "3")))
RETRY_BACKOFF = float(os.environ.get("SCRAPE_RETRY_BACKOFF", "2"))
RETRYABLE_STATUS = {429, 502, 503, 504}
FAST_SKIP_AFTER = int(os.environ.get("SCRAPE_FAST_SKIP_AFTER", "15"))
FAST_SKIP_JUMP = int(os.environ.get("SCRAPE_FAST_SKIP_JUMP", "50"))
SCRAPE_RESUME_PAGE_KEY = "scrape_resume_page"
SCRAPE_LAST_SCAN_KEY = "scrape_last_scan"
SCRAPE_PENDING_KEY = "scrape_pending_candidates"
SCRAPE_QUEUE_META_KEY = "scrape_queue_meta"


def _scrape_http_client(**kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(DETAIL_TIMEOUT, connect=15.0),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        **kwargs,
    )


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


def get_pending_candidates(db: Database) -> list[dict[str, Any]]:
    raw = db.get_meta(SCRAPE_PENDING_KEY, "[]")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def set_pending_candidates(db: Database, candidates: list[dict[str, Any]]) -> None:
    db.set_meta(SCRAPE_PENDING_KEY, json.dumps(candidates, ensure_ascii=False))


def save_queue_meta(
    db: Database,
    *,
    pages_scanned: int,
    skipped: int,
    skipped_duplicates: int,
    start_page: int,
    candidates_found: int,
) -> None:
    db.set_meta(
        SCRAPE_QUEUE_META_KEY,
        json.dumps(
            {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "pages_scanned": pages_scanned,
                "skipped": skipped,
                "skipped_duplicates": skipped_duplicates,
                "start_page": start_page,
                "candidates_found": candidates_found,
                "resume_page": _get_resume_page(db),
            },
            ensure_ascii=False,
        ),
    )


def scrape_state(db: Database) -> dict[str, Any]:
    items = get_pending_candidates(db)
    last_scan: dict[str, Any] | None = None
    raw_last = db.get_meta(SCRAPE_LAST_SCAN_KEY, "")
    if raw_last:
        try:
            last_scan = json.loads(raw_last)
        except json.JSONDecodeError:
            last_scan = None

    queue_meta: dict[str, Any] | None = None
    raw_meta = db.get_meta(SCRAPE_QUEUE_META_KEY, "")
    if raw_meta:
        try:
            queue_meta = json.loads(raw_meta)
        except json.JSONDecodeError:
            queue_meta = None

    return {
        "pending_count": len(items),
        "pending": [
            {"id": m.get("id"), "title": m.get("title"), "year": m.get("year")}
            for m in items[:50]
        ],
        "resume_page": _get_resume_page(db),
        "movies_in_db": db.count_movies(),
        "last_scan": last_scan,
        "queue_meta": queue_meta,
    }


def _load_queue_meta(db: Database) -> dict[str, Any] | None:
    raw = db.get_meta(SCRAPE_QUEUE_META_KEY, "")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def pending_status(db: Database) -> dict[str, Any]:
    state = scrape_state(db)
    return {
        "pending_count": state["pending_count"],
        "pending": state["pending"],
    }


def _apply_scan_resume(db: Database, scan: dict[str, Any], logs: list[str], *, background: bool) -> None:
    page_limit = PAGES_PER_RUN if background else PAGES_PER_RUN_MANUAL
    if scan["hit_page_limit"]:
        if background:
            logs.append(
                f"Auto: przeskanowano {page_limit} stron — kontynuacja od str. {scan['next_page']}."
            )
        else:
            logs.append(
                f"Limit skanowania: {page_limit} stron "
                f"(kontynuacja od str. {scan['next_page']} przy następnym skanie)."
            )
    elif scan["early_stop"]:
        next_page = scan["next_page"] + 1
        _set_resume_page(db, next_page)
        logs.append(f"Auto: najnowsze filmy już w bazie — następne skanowanie od strony {next_page}.")
        return
    elif scan["catalog_end"] and not background:
        logs.append(f"Koniec listy YTS (strona {scan['next_page']}).")

    if scan["catalog_end"]:
        _set_resume_page(db, 1)
        logs.append("Koniec katalogu YTS — następne skanowanie od strony 1.")
    elif not scan["early_stop"]:
        _set_resume_page(db, scan["next_page"])
        if not any("następne skanowanie" in line.lower() for line in logs):
            logs.append(f"Następne skanowanie: strona {scan['next_page']}.")


async def fetch_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    allow_404: bool = False,
    timeout: float = 30.0,
    base_url: str | None = None,
    **params: str,
) -> dict | None:
    bases = [base_url] if base_url else YTS_MIRROR_URLS
    last_exc: Exception | None = None
    for attempt in range(DETAIL_RETRIES):
        for base in bases:
            try:
                res = await client.get(f"{base}/{path}", params=params, timeout=timeout)
                if allow_404 and res.status_code == 404:
                    return None
                res.raise_for_status()
                data = res.json()
                if data.get("status") != "ok":
                    raise RuntimeError(data.get("status_message", "YTS error"))
                return data["data"]
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code not in RETRYABLE_STATUS:
                    raise
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
        if attempt < DETAIL_RETRIES - 1:
            await asyncio.sleep(RETRY_BACKOFF * (attempt + 1))
    if last_exc:
        raise last_exc
    raise RuntimeError("YTS request failed")


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


def _listing_candidates_from_page(
    movies: list[dict[str, Any]],
    *,
    known_ids: set[int],
    known_titles: set[str],
    need_count: int,
    candidates: list[dict[str, Any]],
) -> tuple[int, int, bool]:
    skipped = 0
    skipped_duplicates = 0
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
    return skipped, skipped_duplicates, page_had_new


async def _fetch_listing_page(client: httpx.AsyncClient, page: int) -> tuple[int, list[dict[str, Any]] | None]:
    data = await fetch_json(
        client,
        "list_movies.json",
        timeout=LISTING_TIMEOUT,
        limit=str(PAGE_SIZE),
        page=str(page),
        sort_by="date_added",
        order_by="desc",
    )
    if data is None:
        return page, None
    return page, data.get("movies") or []


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
    if background:
        return await _scan_listing_sequential(
            client,
            start_page=start_page,
            page_limit=page_limit,
            need_count=need_count,
            known_ids=known_ids,
            known_titles=known_titles,
        )
    return await _scan_listing_parallel(
        client,
        start_page=start_page,
        page_limit=page_limit,
        need_count=need_count,
        known_ids=known_ids,
        known_titles=known_titles,
    )


async def _scan_listing_sequential(
    client: httpx.AsyncClient,
    *,
    start_page: int,
    page_limit: int,
    need_count: int,
    known_ids: set[int],
    known_titles: set[str],
) -> dict[str, Any]:
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

        _, movies = await _fetch_listing_page(client, page)
        if movies is None:
            catalog_end = True
            break
        if not movies:
            catalog_end = True
            break

        page_skipped, page_dup, page_had_new = _listing_candidates_from_page(
            movies,
            known_ids=known_ids,
            known_titles=known_titles,
            need_count=need_count,
            candidates=candidates,
        )
        skipped += page_skipped
        skipped_duplicates += page_dup

        if not page_had_new:
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
        await asyncio.sleep(0.1)

    return {
        "candidates": candidates,
        "skipped": skipped,
        "skipped_duplicates": skipped_duplicates,
        "pages_scanned": pages_scanned,
        "next_page": page,
        "catalog_end": catalog_end,
        "hit_page_limit": hit_page_limit,
        "early_stop": early_stop,
        "notes": [],
    }


async def _scan_listing_parallel(
    client: httpx.AsyncClient,
    *,
    start_page: int,
    page_limit: int,
    need_count: int,
    known_ids: set[int],
    known_titles: set[str],
) -> dict[str, Any]:
    """Manual scan: fetch several listing pages in parallel + skip ahead over duplicate blocks."""
    candidates: list[dict[str, Any]] = []
    skipped = 0
    skipped_duplicates = 0
    pages_scanned = 0
    page = start_page
    catalog_end = False
    hit_page_limit = False
    consecutive_full_skip_pages = 0
    notes: list[str] = []

    while len(candidates) < need_count and page <= MAX_PAGES:
        if pages_scanned >= page_limit:
            hit_page_limit = True
            break

        batch_size = min(PARALLEL_LIST_PAGES, page_limit - pages_scanned, MAX_PAGES - page + 1)
        if batch_size <= 0:
            break

        batch_pages = list(range(page, page + batch_size))
        results = await asyncio.gather(
            *[_fetch_listing_page(client, p) for p in batch_pages],
            return_exceptions=True,
        )

        batch_had_new = False
        last_processed = page - 1
        for page_num, result in zip(batch_pages, results):
            pages_scanned += 1
            last_processed = page_num
            if pages_scanned > page_limit:
                hit_page_limit = True
                break
            if isinstance(result, Exception):
                notes.append(f"Strona {page_num}: błąd listy ({result})")
                continue
            _, movies = result
            if movies is None:
                catalog_end = True
                break
            if not movies:
                catalog_end = True
                break

            page_skipped, page_dup, page_had_new = _listing_candidates_from_page(
                movies,
                known_ids=known_ids,
                known_titles=known_titles,
                need_count=need_count,
                candidates=candidates,
            )
            skipped += page_skipped
            skipped_duplicates += page_dup
            if page_had_new:
                batch_had_new = True

            if len(candidates) >= need_count:
                break

        if catalog_end or hit_page_limit or len(candidates) >= need_count:
            page = last_processed + 1
            break

        if not batch_had_new:
            consecutive_full_skip_pages += len(batch_pages)
            if consecutive_full_skip_pages >= FAST_SKIP_AFTER:
                jump_from = last_processed + 1
                page = jump_from + FAST_SKIP_JUMP
                notes.append(
                    f"Przeskok str. {jump_from} → {page} "
                    f"({FAST_SKIP_JUMP} str. samych duplikatów — szybszy skan)."
                )
                consecutive_full_skip_pages = 0
            else:
                page = last_processed + 1
        else:
            consecutive_full_skip_pages = 0
            page = last_processed + 1

    return {
        "candidates": candidates,
        "skipped": skipped,
        "skipped_duplicates": skipped_duplicates,
        "pages_scanned": pages_scanned,
        "next_page": page,
        "catalog_end": catalog_end,
        "hit_page_limit": hit_page_limit,
        "early_stop": False,
        "notes": notes,
    }


def _log_scan_summary(
    logs: list[str],
    *,
    background: bool,
    start_page: int,
    scan: dict[str, Any],
    scan_only: bool = False,
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
        logs.append(f"Znaleziono {len(candidates)} nowych filmów:")
        for m in candidates[:12]:
            logs.append(f"  → {m.get('title', '?')} (id={m.get('id')})")
        if len(candidates) > 12:
            logs.append(f"  … i {len(candidates) - 12} więcej")
        if scan_only:
            logs.append("Zapisano w kolejce — kliknij „Pobierz”, aby dodać do bazy.")
        else:
            logs.append("Pobieranie szczegółów z YTS…")
    else:
        logs.append("W tym zakresie brak nowych filmów.")


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
        try:
            detail = await fetch_json(
                client,
                "movie_details.json",
                timeout=DETAIL_TIMEOUT,
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
        except Exception as exc:
            msg = f"Pominięto {title} (id={mid}): {exc}"
            logs.append(msg)
            if background:
                logger.warning(msg)
        await asyncio.sleep(0.1 if background else 0.25)
    return detailed


async def _save_scraped_movies(
    db: Database,
    detailed: list[dict[str, Any]],
    logs: list[str],
) -> tuple[int, list[str]]:
    saved = db.upsert_movies(detailed)
    batch_ids = [int(m["id"]) for m in detailed]
    db.set_last_batch_ids(batch_ids)
    known_ids = db.existing_ids()
    upcoming, upcoming_note = [], None
    if detailed:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            upcoming, upcoming_note = await fetch_upcoming(client, detailed)
    upcoming = [m for m in upcoming if int(m.get("id") or 0) in known_ids]
    db.set_upcoming(upcoming)
    db.set_meta("last_scrape", datetime.now(timezone.utc).isoformat())
    db.set_meta("last_scrape_count", str(saved))
    if saved:
        MovieStore.invalidate_dup_cache()

    seo_urls = register_movies_for_seo(db, detailed)
    if seo_urls:
        logs.append(f"SEO: {len(seo_urls)} nowych stron gotowych (meta, bez dodawania do sitemap).")
        for url in seo_urls:
            logs.append(f"  → {url}")
    elif saved == 0:
        logs.append("SEO: brak nowych stron.")
    if upcoming_note:
        logs.append(upcoming_note)
    return saved, seo_urls


async def scan_listings_only(count: int = 10) -> dict[str, Any]:
    """Manual phase 1: scan YTS lists and queue candidates — no detail fetch."""
    count = max(1, int(count))
    logs: list[str] = []
    db = Database()
    known_ids = db.existing_ids()
    known_titles = db.existing_titles()
    start_page = _get_resume_page(db)

    if start_page > 1:
        logs.append(f"Kontynuacja od strony {start_page} (katalog YTS, sort. date_added).")

    async with _scrape_http_client() as client:
        scan = await _scan_listing_candidates(
            client,
            start_page=start_page,
            page_limit=PAGES_PER_RUN_MANUAL,
            need_count=count,
            known_ids=known_ids,
            known_titles=known_titles,
            background=False,
        )

    _log_scan_summary(logs, background=False, start_page=start_page, scan=scan, scan_only=True)
    for note in scan.get("notes") or []:
        logs.append(note)
    if scan["skipped"] and not scan["candidates"]:
        logs.append(f"Pominięto {scan['skipped']} filmów już w bazie (po ID).")
    if scan["skipped_duplicates"] and not scan["candidates"]:
        logs.append(f"Pominięto {scan['skipped_duplicates']} filmów z powtarzającym się tytułem.")

    set_pending_candidates(db, scan["candidates"])
    save_queue_meta(
        db,
        pages_scanned=scan["pages_scanned"],
        skipped=scan["skipped"],
        skipped_duplicates=scan["skipped_duplicates"],
        start_page=start_page,
        candidates_found=len(scan["candidates"]),
    )
    _apply_scan_resume(db, scan, logs, background=False)
    _save_last_scan(db, background=False, start_page=start_page, scan=scan, saved=0)

    return {
        "saved": 0,
        "skipped": scan["skipped"],
        "skipped_duplicates": scan["skipped_duplicates"],
        "candidates_found": len(scan["candidates"]),
        "pending_count": len(scan["candidates"]),
        "pages_scanned": scan["pages_scanned"],
        "resume_page": _get_resume_page(db),
        "start_page": start_page,
        "total_in_db": db.count_movies(),
        "logs": logs,
    }


async def download_pending_movies(count: int = 10) -> dict[str, Any]:
    """Manual phase 2: fetch details for queued candidates from last scan."""
    count = max(1, int(count))
    logs: list[str] = []
    db = Database()
    pending = get_pending_candidates(db)
    if not pending:
        logs.append("Kolejka pusta — najpierw kliknij „Skanuj”.")
        return {
            "saved": 0,
            "skipped": 0,
            "skipped_duplicates": 0,
            "candidates_found": 0,
            "pending_count": 0,
            "pages_scanned": 0,
            "resume_page": _get_resume_page(db),
            "total_in_db": db.count_movies(),
            "logs": logs,
        }

    batch = pending[:count]
    remaining = pending[count:]
    logs.append(f"Pobieranie {len(batch)} z {len(pending)} filmów z kolejki…")

    known_ids = db.existing_ids()
    known_titles = db.existing_titles()
    async with _scrape_http_client() as client:
        detailed = await _fetch_candidate_details(
            client,
            batch,
            known_ids=known_ids,
            known_titles=known_titles,
            background=False,
            logs=logs,
        )

    set_pending_candidates(db, remaining)
    queue_meta = _load_queue_meta(db)
    if remaining and queue_meta:
        queue_meta["candidates_found"] = len(remaining)
        queue_meta["saved_at"] = datetime.now(timezone.utc).isoformat()
        db.set_meta(SCRAPE_QUEUE_META_KEY, json.dumps(queue_meta, ensure_ascii=False))
    elif not remaining:
        db.set_meta(SCRAPE_QUEUE_META_KEY, "")
    saved, seo_urls = await _save_scraped_movies(db, detailed, logs)

    if not detailed:
        logs.append("Nic nie pobrano.")
    elif len(batch) < count:
        logs.append(f"Pobrano {len(detailed)} filmów (kolejka wyczerpana).")
    else:
        logs.append(f"Dodano {saved} filmów. W kolejce zostało: {len(remaining)}.")

    scan_stub = {
        "candidates": batch,
        "pages_scanned": 0,
        "skipped": 0,
        "skipped_duplicates": 0,
    }
    _save_last_scan(db, background=False, start_page=_get_resume_page(db), scan=scan_stub, saved=saved)

    return {
        "saved": saved,
        "skipped": 0,
        "skipped_duplicates": 0,
        "candidates_found": len(batch),
        "pending_count": len(remaining),
        "pages_scanned": 0,
        "resume_page": _get_resume_page(db),
        "seo_urls": seo_urls,
        "sitemap_url": f"{SITE_URL}/sitemap.xml" if SITE_URL else "/sitemap.xml",
        "source": YTS_BASE,
        "total_in_db": db.count_movies(),
        "logs": logs,
    }


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

    async with _scrape_http_client() as client:
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

        if not detailed:
            if background:
                pass
            else:
                logs.append("Brak nowych filmów do dodania w tym zakresie stron.")
        elif background and detailed:
            logs.append(f"Auto: dodano {len(detailed)} nowych filmów.")

        _apply_scan_resume(db, scan, logs, background=background)

        upcoming, upcoming_note = await fetch_upcoming(client, detailed)
        if upcoming_note and not background:
            logs.append(upcoming_note)

    saved = db.upsert_movies(detailed)
    batch_ids = [int(m["id"]) for m in detailed]
    db.set_last_batch_ids(batch_ids)
    known_ids = db.existing_ids()
    upcoming = [m for m in upcoming if int(m.get("id") or 0) in known_ids]
    db.set_upcoming(upcoming)
    db.set_meta("last_scrape", datetime.now(timezone.utc).isoformat())
    db.set_meta("last_scrape_count", str(saved))
    if saved:
        MovieStore.invalidate_dup_cache()

    seo_urls = register_movies_for_seo(db, detailed)
    if seo_urls:
        logs.append(f"SEO: {len(seo_urls)} nowych stron gotowych (meta, bez dodawania do sitemap).")
        for url in seo_urls:
            logs.append(f"  → {url}")
    elif saved == 0:
        logs.append("SEO: brak nowych stron.")

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
