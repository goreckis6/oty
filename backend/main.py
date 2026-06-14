from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from scrape_cache import DATA_SOURCE, ScrapeCache
from sources import (
    APIBAY_URL,
    TMDB_KEY,
    TORRENT_SOURCE,
    TORZNAB_URL,
    TorrentSearch,
    TmdbClient,
    ok,
)

API_PREFIX = "/api/v1"

tmdb: TmdbClient | None = None
torrents: TorrentSearch | None = None
cache: ScrapeCache | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global tmdb, torrents, cache
    if DATA_SOURCE == "scrape":
        cache = ScrapeCache()
    elif TMDB_KEY:
        tmdb = TmdbClient(TMDB_KEY)
    torrents = TorrentSearch()
    yield
    if tmdb:
        await tmdb.close()
    if torrents:
        await torrents.close()


app = FastAPI(title="YTS API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def require_tmdb() -> TmdbClient:
    if not TMDB_KEY:
        raise HTTPException(
            status_code=503,
            detail="Set TMDB_API_KEY or DATA_SOURCE=scrape",
        )
    assert tmdb is not None
    return tmdb


def require_cache() -> ScrapeCache:
    if cache is None:
        raise HTTPException(status_code=503, detail="Scrape cache not loaded")
    return cache


@app.get(f"{API_PREFIX}/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "data_source": DATA_SOURCE,
        "movies_cached": len(cache.movies) if cache else 0,
        "tmdb_configured": bool(TMDB_KEY),
        "torrents": TORRENT_SOURCE,
        "torznab_configured": bool(TORZNAB_URL),
        "apibay_url": APIBAY_URL if TORRENT_SOURCE == "apibay" else None,
    }


@app.get(f"{API_PREFIX}/list_movies.json")
async def list_movies(request: Request) -> JSONResponse:
    params = dict(request.query_params)
    if DATA_SOURCE == "scrape":
        data = require_cache().list_movies(params)
        return JSONResponse(ok(data, source="yts.bz scrape"))
    client = require_tmdb()
    data = await client.list_movies(params)
    return JSONResponse(ok(data))


@app.get(f"{API_PREFIX}/list_upcoming.json")
async def list_upcoming() -> JSONResponse:
    if DATA_SOURCE == "scrape":
        data = require_cache().list_upcoming()
        return JSONResponse(ok(data))
    client = require_tmdb()
    data = await client.list_upcoming()
    return JSONResponse(ok(data))


@app.get(f"{API_PREFIX}/movie_suggestions.json")
async def movie_suggestions(request: Request) -> JSONResponse:
    movie_id = request.query_params.get("movie_id")
    slug = request.query_params.get("slug")
    if not movie_id and not slug:
        raise HTTPException(status_code=400, detail="movie_id or slug required")
    if DATA_SOURCE == "scrape":
        data = require_cache().movie_suggestions(
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

    if DATA_SOURCE == "scrape":
        try:
            data = require_cache().movie_details(
                int(movie_id) if movie_id else None,
                slug,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JSONResponse(ok(data))

    client = require_tmdb()
    data = await client.movie_details(int(movie_id))
    movie = data["movie"]
    quality = request.query_params.get("quality")
    if torrents:
        found = await torrents.search(movie["title"], movie["year"], quality)
        movie["torrents"] = found
    return JSONResponse(ok(data))


@app.get(f"{API_PREFIX}/movie_comments.json")
async def movie_comments() -> JSONResponse:
    return JSONResponse(ok({"comments": []}))


@app.get(f"{API_PREFIX}/movie_reviews.json")
async def movie_reviews() -> JSONResponse:
    return JSONResponse(ok({"reviews": []}))
