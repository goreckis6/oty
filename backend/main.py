import asyncio
import base64
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from analytics import AnalyticsTracker
from auth import (
    ADMIN_USER,
    TOKEN_COOKIE,
    TOKEN_TTL_HOURS,
    assert_admin_client,
    authenticate,
    client_ip,
    client_country,
    create_token,
    require_admin,
)
from auto_scraper import (
    AutoScrapeService,
    run_download_locked,
    run_scan_locked,
    run_scrape_locked,
    start_auto_scraper,
    stop_auto_scraper,
)
from database import COUNT_CACHE_KEY, Database
from movie_store import MovieStore
from scraper import scrape_state
from seo import (
    build_robots,
    build_sitemap,
    build_sitemap_part,
    build_yandex_sitemap,
    build_yandex_sitemap_part,
    register_movies_for_seo,
    render_movie_page,
)
from site_files import delete_site_file, list_site_files, read_site_file, upload_site_file, write_site_file
from site_branding import get_branding, remove_logo, save_branding, save_logo
from sources import (
    APIBAY_URL,
    DATA_SOURCE,
    TMDB_KEY,
    TORRENT_SOURCE,
    TORZNAB_URL,
    TorrentSearch,
    TmdbClient,
    ok,
)
from torrent_proxy import TorrentProxy, cache_path, normalize_hash

API_PREFIX = "/api/v1"
PUBLIC_DIR = Path(os.environ.get("PUBLIC_DIR", "/app/public"))

tmdb: TmdbClient | None = None
torrents: TorrentSearch | None = None
torrent_proxy: TorrentProxy | None = None
store: MovieStore | None = None
db: Database | None = None
analytics: AnalyticsTracker | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global tmdb, torrents, torrent_proxy, store, db, analytics
    db = Database(defer_maintenance=True)
    analytics = AnalyticsTracker(db)
    if DATA_SOURCE in ("sqlite", "scrape"):
        store = MovieStore(db)
    elif TMDB_KEY:
        tmdb = TmdbClient(TMDB_KEY)
    torrents = TorrentSearch()
    torrent_proxy = TorrentProxy()
    await torrent_proxy.start()
    if DATA_SOURCE in ("sqlite", "scrape"):
        start_auto_scraper(db)
    asyncio.create_task(asyncio.to_thread(db.run_startup_maintenance), name="db-startup-maintenance")
    yield
    await stop_auto_scraper()
    if tmdb:
        await tmdb.close()
    if torrents:
        await torrents.close()
    if torrent_proxy:
        await torrent_proxy.close()


app = FastAPI(title="YTS API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def admin_access_guard(request: Request, call_next):
    path = request.url.path
    is_admin_api = path.startswith(f"{API_PREFIX}/admin")
    is_admin_page = path == "/twojastara"
    if is_admin_api or is_admin_page:
        try:
            assert_admin_client(request)
        except HTTPException as exc:
            if is_admin_api:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            return PlainTextResponse("Not Found", status_code=404)
    return await call_next(request)


class LoginRequest(BaseModel):
    password: str


class ScrapeRequest(BaseModel):
    count: int = Field(default=10, ge=1)


class AutoScrapeRequest(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(default=60, ge=2, le=1440)
    count: int = Field(default=10, ge=1)


class BulkDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


class SiteFileWriteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=200)
    content: str = ""
    overwrite: bool = True


class BrandingRequest(BaseModel):
    site_name: str = Field(default="", max_length=40)
    site_tagline: str = Field(default="", max_length=120)


class AnalyticsPingRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)
    path: str = Field(default="/", max_length=500)


def require_tmdb() -> TmdbClient:
    if not TMDB_KEY:
        raise HTTPException(status_code=503, detail="Set TMDB_API_KEY")
    assert tmdb is not None
    return tmdb


def require_store() -> MovieStore:
    if store is None:
        raise HTTPException(status_code=503, detail="Movie store not loaded")
    return store


def use_store() -> bool:
    return DATA_SOURCE in ("sqlite", "scrape") and store is not None


def _read_index_html() -> str:
    index = PUBLIC_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=503, detail="Frontend not found")
    return index.read_text(encoding="utf-8")


def _spa_html(bootstrap: str = "") -> HTMLResponse:
    html = _read_index_html()
    if bootstrap:
        html = html.replace(
            '  <script src="/js/config.js"></script>',
            f"  {bootstrap}\n  <script src=\"/js/config.js\"></script>",
        )
    return HTMLResponse(content=html, headers={"Cache-Control": "no-cache"})


def _spa_index() -> HTMLResponse:
    return _spa_html()


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def spa_home() -> HTMLResponse:
    bootstrap = ""
    if use_store() and store is not None:
        data = store.list_movies(
            {"limit": "20", "sort_by": "date_added", "order_by": "desc"}
        )
        bootstrap = (
            "<script>window.__HOME_MOVIES__="
            f"{json.dumps(data, ensure_ascii=False)}</script>"
        )
    return _spa_html(bootstrap)


@app.get("/browse", response_class=HTMLResponse, include_in_schema=False)
async def spa_browse() -> HTMLResponse:
    return _spa_index()


@app.get("/twojastara", response_class=HTMLResponse, include_in_schema=False)
async def spa_admin() -> HTMLResponse:
    bootstrap = (
        '<script>window.__ADMIN_PAGE__=true</script>'
        '<link rel="preload" href="/js/admin.js" as="script">'
        '<script src="/js/admin.js" defer></script>'
    )
    return _spa_html(bootstrap)


@app.get(f"{API_PREFIX}/health")
async def health() -> dict[str, Any]:
    movies_in_db: int | None = None
    if db:
        cached = db.get_meta(COUNT_CACHE_KEY, "")
        if cached.isdigit():
            movies_in_db = int(cached)
    return {
        "status": "ok",
        "data_source": DATA_SOURCE,
        "movies_in_db": movies_in_db,
        "tmdb_configured": bool(TMDB_KEY),
        "torrents": TORRENT_SOURCE,
    }


@app.get(f"{API_PREFIX}/myip")
async def my_ip(request: Request) -> dict[str, str]:
    """Public helper: shows your public IP as used for ADMIN_ALLOWED_IPS."""
    peer = request.client.host if request.client else ""
    return {
        "ip": client_ip(request),
        "peer": peer or "",
        "x_forwarded_for": request.headers.get("x-forwarded-for") or "",
        "x_real_ip": request.headers.get("x-real-ip") or "",
    }


def _decode_go_param(value: str) -> str:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode()).decode("utf-8", errors="strict")


def _allowed_download_target(url: str) -> bool:
    if url.startswith("magnet:?"):
        return "xt=urn:btih:" in url.lower()
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        return False
    if not parsed.netloc:
        return False
    host = parsed.hostname or ""
    if host in ("localhost", "127.0.0.1", "::1"):
        return False
    if host.startswith("10.") or host.startswith("192.168.") or host.startswith("172."):
        return False
    return True


@app.get(f"{API_PREFIX}/go", include_in_schema=False)
async def go_download(request: Request) -> RedirectResponse:
    raw = (request.query_params.get("u") or request.query_params.get("m") or "").strip()
    if not raw:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        target = _decode_go_param(raw)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=404, detail="Not found") from None
    if not _allowed_download_target(target):
        raise HTTPException(status_code=404, detail="Not found")
    return RedirectResponse(url=target, status_code=302)


@app.get(f"{API_PREFIX}/torrent/{{info_hash}}", include_in_schema=False)
async def torrent_download(info_hash: str, request: Request) -> Response:
    normalized = normalize_hash(info_hash)
    if not normalized:
        raise HTTPException(status_code=404, detail="Not found")
    if torrent_proxy is None:
        raise HTTPException(status_code=503, detail="Unavailable")

    cached_file = cache_path(normalized)
    if cached_file.is_file():
        return FileResponse(
            cached_file,
            media_type="application/x-bittorrent",
            filename=f"{normalized}.torrent",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    fallback_url: str | None = None
    raw_src = (request.query_params.get("src") or "").strip()
    if raw_src:
        try:
            candidate = _decode_go_param(raw_src)
        except (ValueError, UnicodeDecodeError):
            candidate = ""
        if candidate and _allowed_download_target(candidate):
            fallback_url = candidate

    data = await torrent_proxy.fetch(normalized, fallback_url)
    if not data:
        raise HTTPException(status_code=404, detail="Torrent not found")
    filename = f"{normalized}.torrent"
    return Response(
        content=data,
        media_type="application/x-bittorrent",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )


@app.get(f"{API_PREFIX}/site/branding")
async def site_branding() -> dict[str, Any]:
    assert db is not None
    return {"status": "ok", **get_branding(db)}


@app.post(f"{API_PREFIX}/admin/login")
async def admin_login(body: LoginRequest) -> JSONResponse:
    if not authenticate(body.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(ADMIN_USER)
    site_url = os.environ.get("SITE_URL", "")
    resp = JSONResponse({"token": token, "status": "ok"})
    resp.set_cookie(
        key=TOKEN_COOKIE,
        value=token,
        max_age=TOKEN_TTL_HOURS * 3600,
        httponly=True,
        secure=site_url.startswith("https"),
        samesite="lax",
        path="/",
    )
    return resp


@app.post(f"{API_PREFIX}/admin/logout")
async def admin_logout() -> JSONResponse:
    resp = JSONResponse({"status": "ok"})
    resp.delete_cookie(key=TOKEN_COOKIE, path="/")
    return resp


@app.get(f"{API_PREFIX}/admin/me")
async def admin_me(username: str = Depends(require_admin)) -> dict[str, str]:
    return {"username": username, "status": "ok"}


@app.get(f"{API_PREFIX}/admin/stats")
async def admin_stats(_: str = Depends(require_admin)) -> dict[str, Any]:
    assert db is not None
    new_count = len(db.get_last_batch_ids())
    active_now = 0
    if analytics is not None:
        active_now = await asyncio.to_thread(analytics.active_count)
    return {
        "movies_count": db.count_movies(),
        "last_scrape": db.get_meta("last_scrape"),
        "last_scrape_count": db.get_meta("last_scrape_count"),
        "new_count": new_count,
        "data_source": DATA_SOURCE,
        "scrape_resume_page": db.get_meta("scrape_resume_page", "1"),
        "active_now": active_now,
    }


@app.get(f"{API_PREFIX}/admin/analytics")
async def admin_analytics(_: str = Depends(require_admin)) -> dict[str, Any]:
    if analytics is None:
        raise HTTPException(status_code=503, detail="Analytics unavailable")
    return await asyncio.to_thread(analytics.get_stats)


@app.post(f"{API_PREFIX}/analytics/ping")
async def analytics_ping(
    request: Request,
    background_tasks: BackgroundTasks,
    body: AnalyticsPingRequest,
) -> dict[str, str]:
    if analytics is not None:
        ip = client_ip(request)
        ua = request.headers.get("user-agent")
        country = client_country(request)
        background_tasks.add_task(
            analytics.record_ping, body.session_id, body.path, ip, ua, country
        )
    return {"status": "ok"}


@app.get(f"{API_PREFIX}/admin/bootstrap")
async def admin_bootstrap(
    request: Request,
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    """Single round-trip for admin dashboard initial load."""
    assert db is not None
    store = require_store()
    page = max(1, int(request.query_params.get("page") or 1))
    limit = int(request.query_params.get("limit") or 50)
    sort_by = request.query_params.get("sort_by") or "updated_at"
    order = request.query_params.get("order") or "desc"
    new_count = len(db.get_last_batch_ids())
    movies = store.list_all_admin(page=page, limit=limit, sort_by=sort_by, order=order)
    return {
        "status": "ok",
        "movies_count": movies["movie_count"],
        "last_scrape": db.get_meta("last_scrape"),
        "last_scrape_count": db.get_meta("last_scrape_count"),
        "new_count": new_count,
        "data_source": DATA_SOURCE,
        "scrape_resume_page": db.get_meta("scrape_resume_page", "1"),
        **movies,
    }


@app.get(f"{API_PREFIX}/admin/movies")
async def admin_movies(
    request: Request,
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    store = require_store()
    page = max(1, int(request.query_params.get("page") or 1))
    limit = int(request.query_params.get("limit") or 50)
    sort_by = request.query_params.get("sort_by") or "updated_at"
    order = request.query_params.get("order") or "desc"
    data = store.list_all_admin(page=page, limit=limit, sort_by=sort_by, order=order)
    return {"status": "ok", "new_count": len(store.new_ids), **data}


@app.delete(f"{API_PREFIX}/admin/movies/{{movie_id}}")
async def admin_delete_movie(
    movie_id: int,
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    assert db is not None
    if not db.delete_movie(movie_id):
        raise HTTPException(status_code=404, detail="Movie not found")
    MovieStore.invalidate_dup_cache()
    return {
        "status": "ok",
        "deleted_id": movie_id,
        "total_in_db": db.count_movies(),
    }


@app.post(f"{API_PREFIX}/admin/movies/bulk-delete")
async def admin_bulk_delete_movies(
    body: BulkDeleteRequest,
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    assert db is not None
    unique_ids = list(dict.fromkeys(body.ids))
    deleted = db.delete_movies(unique_ids)
    MovieStore.invalidate_dup_cache()
    return {
        "status": "ok",
        "deleted": deleted,
        "requested": len(unique_ids),
        "total_in_db": db.count_movies(),
    }


@app.get(f"{API_PREFIX}/admin/scrape/queue")
async def admin_scrape_queue(_: str = Depends(require_admin)) -> dict[str, Any]:
    assert db is not None
    return {"status": "ok", **scrape_state(db)}


@app.post(f"{API_PREFIX}/admin/scrape/scan")
async def admin_scrape_scan(
    body: ScrapeRequest,
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    try:
        result = await run_scan_locked(body.count)
        return {"status": "ok", **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post(f"{API_PREFIX}/admin/scrape")
async def admin_scrape(
    body: ScrapeRequest,
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    try:
        result = await run_download_locked(body.count)
        MovieStore.invalidate_dup_cache()
        return {"status": "ok", **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get(f"{API_PREFIX}/admin/auto-scrape")
async def admin_auto_scrape_get(_: str = Depends(require_admin)) -> dict[str, Any]:
    assert db is not None
    return {"status": "ok", **AutoScrapeService(db).get_settings()}


@app.post(f"{API_PREFIX}/admin/auto-scrape")
async def admin_auto_scrape_save(
    body: AutoScrapeRequest,
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    assert db is not None
    settings = AutoScrapeService(db).save_settings(
        enabled=body.enabled,
        interval_minutes=body.interval_minutes,
        count=body.count,
    )
    return {"status": "ok", **settings}


@app.get(f"{API_PREFIX}/admin/files")
async def admin_list_files(_: str = Depends(require_admin)) -> dict[str, Any]:
    return {"status": "ok", "files": list_site_files()}


@app.get(f"{API_PREFIX}/admin/files/content")
async def admin_read_file(
    request: Request,
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    path = request.query_params.get("path", "")
    try:
        return {"status": "ok", **read_site_file(path)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put(f"{API_PREFIX}/admin/files")
async def admin_write_file(
    body: SiteFileWriteRequest,
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    try:
        info = write_site_file(body.path, body.content, overwrite=body.overwrite)
        return {"status": "ok", "file": info}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(f"{API_PREFIX}/admin/files/upload")
async def admin_upload_file(
    path: str = Form(...),
    file: UploadFile = File(...),
    overwrite: bool = Form(default=True),
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    data = await file.read()
    try:
        info = upload_site_file(path, data, overwrite=overwrite)
        return {"status": "ok", "file": info}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete(f"{API_PREFIX}/admin/files")
async def admin_delete_file(
    request: Request,
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    path = request.query_params.get("path", "")
    try:
        delete_site_file(path)
        return {"status": "ok", "deleted": path}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get(f"{API_PREFIX}/admin/branding")
async def admin_branding_get(_: str = Depends(require_admin)) -> dict[str, Any]:
    assert db is not None
    return {"status": "ok", **get_branding(db)}


@app.post(f"{API_PREFIX}/admin/branding")
async def admin_branding_save(
    body: BrandingRequest,
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    assert db is not None
    branding = save_branding(
        db,
        site_name=body.site_name,
        site_tagline=body.site_tagline,
    )
    return {"status": "ok", **branding}


@app.post(f"{API_PREFIX}/admin/branding/logo")
async def admin_branding_logo(
    file: UploadFile = File(...),
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    assert db is not None
    data = await file.read()
    try:
        branding = save_logo(db, file.filename or "logo.png", data)
        return {"status": "ok", **branding}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete(f"{API_PREFIX}/admin/branding/logo")
async def admin_branding_logo_delete(_: str = Depends(require_admin)) -> dict[str, Any]:
    assert db is not None
    return {"status": "ok", **remove_logo(db)}


@app.get(f"{API_PREFIX}/list_movies.json")
async def list_movies(request: Request) -> JSONResponse:
    params = dict(request.query_params)
    if use_store():
        data = require_store().list_movies(params)
        return JSONResponse(ok(data, source="sqlite"))
    client = require_tmdb()
    data = await client.list_movies(params)
    return JSONResponse(ok(data))


@app.get(f"{API_PREFIX}/list_upcoming.json")
async def list_upcoming(request: Request) -> JSONResponse:
    limit = min(max(1, int(request.query_params.get("limit") or 20)), 20)
    if use_store():
        return JSONResponse(ok(require_store().list_upcoming(limit=limit)))
    client = require_tmdb()
    data = await client.list_upcoming()
    return JSONResponse(ok(data))


@app.get(f"{API_PREFIX}/movie_suggestions.json")
async def movie_suggestions(request: Request) -> JSONResponse:
    movie_id = request.query_params.get("movie_id")
    slug = request.query_params.get("slug")
    if not movie_id and not slug:
        raise HTTPException(status_code=400, detail="movie_id or slug required")
    if use_store():
        data = require_store().movie_suggestions(
            int(movie_id) if movie_id else None,
            slug,
        )
        return JSONResponse(ok(data))
    client = require_tmdb()
    data = await client.movie_suggestions(int(movie_id))
    return JSONResponse(ok(data))


@app.get(f"{API_PREFIX}/movie_details.json")
async def movie_details(request: Request) -> JSONResponse:
    movie_id = request.query_params.get("movie_id")
    slug = request.query_params.get("slug")
    if not movie_id and not slug:
        raise HTTPException(status_code=400, detail="movie_id or slug required")

    if use_store():
        try:
            data = require_store().movie_details(
                int(movie_id) if movie_id else None,
                slug,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if torrent_proxy:
            torrent_proxy.prefetch_movie(data["movie"])
        return JSONResponse(ok(data))

    client = require_tmdb()
    data = await client.movie_details(int(movie_id))
    movie = data["movie"]
    quality = request.query_params.get("quality")
    if torrents:
        found = await torrents.search(movie["title"], movie["year"], quality)
        movie["torrents"] = found
    if torrent_proxy:
        torrent_proxy.prefetch_movie(movie)
    return JSONResponse(ok(data))


@app.get(f"{API_PREFIX}/movie_comments.json")
async def movie_comments() -> JSONResponse:
    return JSONResponse(ok({"comments": []}))


@app.get(f"{API_PREFIX}/movie_reviews.json")
async def movie_reviews() -> JSONResponse:
    return JSONResponse(ok({"reviews": []}))


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt() -> str:
    return build_robots()


@app.get("/sitemap.xml")
async def sitemap_xml() -> Response:
    assert db is not None
    entries = db.list_sitemap_entries() if use_store() else []
    xml = build_sitemap(entries)
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/sitemap-yandex.xml")
async def sitemap_yandex_xml() -> Response:
    """Full sitemap (homepage + movies) for Yandex Webmaster."""
    assert db is not None
    entries = db.list_sitemap_entries() if use_store() else []
    xml = build_yandex_sitemap(entries)
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/sitemap-yandex{index}.xml")
async def sitemap_yandex_part(index: int) -> Response:
    assert db is not None
    entries = db.list_sitemap_entries() if use_store() else []
    xml = build_yandex_sitemap_part(entries, index)
    if xml is None:
        raise HTTPException(status_code=404, detail="Sitemap not found")
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/sitemap{index}.xml")
async def sitemap_part(index: int) -> Response:
    assert db is not None
    entries = db.list_sitemap_entries() if use_store() else []
    xml = build_sitemap_part(entries, index)
    if xml is None:
        raise HTTPException(status_code=404, detail="Sitemap not found")
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/movies/{slug}", response_class=HTMLResponse)
async def movie_seo_page(slug: str) -> HTMLResponse:
    if not use_store():
        raise HTTPException(status_code=404, detail="Movie not found")
    try:
        data = require_store().movie_details(slug=slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return HTMLResponse(render_movie_page(data["movie"]))


for _static_name in ("css", "js", "uploads", "downloads"):
    _static_dir = PUBLIC_DIR / _static_name
    if _static_dir.is_dir():
        app.mount(
            f"/{_static_name}",
            StaticFiles(directory=_static_dir),
            name=f"static_{_static_name}",
        )
