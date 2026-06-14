from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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


@asynccontextmanager
async def lifespan(_: FastAPI):
    global tmdb, torrents
    if TMDB_KEY:
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
            detail="Set TMDB_API_KEY (free key from themoviedb.org)",
        )
    assert tmdb is not None
    return tmdb


@app.get(f"{API_PREFIX}/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "metadata": "tmdb",
        "torrents": TORRENT_SOURCE,
        "tmdb_configured": bool(TMDB_KEY),
        "torznab_configured": bool(TORZNAB_URL),
        "apibay_url": APIBAY_URL if TORRENT_SOURCE == "apibay" else None,
    }


@app.get(f"{API_PREFIX}/list_movies.json")
async def list_movies(request: Request) -> JSONResponse:
    client = require_tmdb()
    params = dict(request.query_params)
    data = await client.list_movies(params)
    return JSONResponse(ok(data))


@app.get(f"{API_PREFIX}/list_upcoming.json")
async def list_upcoming() -> JSONResponse:
    client = require_tmdb()
    data = await client.list_upcoming()
    return JSONResponse(ok(data))


@app.get(f"{API_PREFIX}/movie_suggestions.json")
async def movie_suggestions(request: Request) -> JSONResponse:
    client = require_tmdb()
    movie_id = request.query_params.get("movie_id")
    if not movie_id:
        raise HTTPException(status_code=400, detail="movie_id required")
    data = await client.movie_suggestions(int(movie_id))
    return JSONResponse(ok(data))


@app.get(f"{API_PREFIX}/movie_details.json")
async def movie_details(request: Request) -> JSONResponse:
    client = require_tmdb()
    movie_id = request.query_params.get("movie_id")
    if not movie_id:
        raise HTTPException(status_code=400, detail="movie_id required")

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
