from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth import authenticate, create_token, require_admin
from database import Database
from movie_store import MovieStore
from scraper import scrape_movies
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

API_PREFIX = "/api/v1"

tmdb: TmdbClient | None = None
torrents: TorrentSearch | None = None
store: MovieStore | None = None
db: Database | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global tmdb, torrents, store, db
    db = Database()
    if DATA_SOURCE in ("sqlite", "scrape"):
        store = MovieStore(db)
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
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    username: str
    password: str


class ScrapeRequest(BaseModel):
    count: int = Field(default=10, ge=1, le=50)


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


@app.get(f"{API_PREFIX}/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "data_source": DATA_SOURCE,
        "movies_in_db": db.count_movies() if db else 0,
        "tmdb_configured": bool(TMDB_KEY),
        "torrents": TORRENT_SOURCE,
    }


@app.post(f"{API_PREFIX}/admin/login")
async def admin_login(body: LoginRequest) -> dict[str, str]:
    if not authenticate(body.username, body.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": create_token(body.username), "status": "ok"}


@app.get(f"{API_PREFIX}/admin/me")
async def admin_me(username: str = Depends(require_admin)) -> dict[str, str]:
    return {"username": username, "status": "ok"}


@app.get(f"{API_PREFIX}/admin/stats")
async def admin_stats(_: str = Depends(require_admin)) -> dict[str, Any]:
    assert db is not None
    new_count = len(db.get_last_batch_ids())
    return {
        "movies_count": db.count_movies(),
        "last_scrape": db.get_meta("last_scrape"),
        "last_scrape_count": db.get_meta("last_scrape_count"),
        "new_count": new_count,
        "data_source": DATA_SOURCE,
    }


@app.get(f"{API_PREFIX}/admin/movies")
async def admin_movies(_: str = Depends(require_admin)) -> dict[str, Any]:
    store = require_store()
    return {
        "status": "ok",
        "movies": store.list_all_admin(),
        "new_count": len(store.new_ids),
    }


@app.delete(f"{API_PREFIX}/admin/movies/{movie_id}")
async def admin_delete_movie(
    movie_id: int,
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    assert db is not None
    if not db.delete_movie(movie_id):
        raise HTTPException(status_code=404, detail="Movie not found")
    return {
        "status": "ok",
        "deleted_id": movie_id,
        "total_in_db": db.count_movies(),
    }


@app.post(f"{API_PREFIX}/admin/scrape")
async def admin_scrape(
    body: ScrapeRequest,
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    try:
        result = await scrape_movies(body.count)
        return {"status": "ok", **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
async def list_upcoming() -> JSONResponse:
    if use_store():
        return JSONResponse(ok(require_store().list_upcoming()))
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
