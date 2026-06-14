import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

UPSTREAM = os.environ.get("YTS_UPSTREAM", "https://yts.bz/api/v2").rstrip("/")
API_PREFIX = "/api/v1"

app = FastAPI(title="YTS API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

PROXY_PATHS = {
    "list_movies.json",
    "movie_details.json",
    "list_upcoming.json",
    "movie_suggestions.json",
    "movie_comments.json",
    "movie_reviews.json",
}


async def proxy_yts(path: str, params: dict[str, Any]) -> JSONResponse:
    url = f"{UPSTREAM}/{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            res = await client.get(url, params=params)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream unreachable: {exc}") from exc

    try:
        payload = res.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Upstream returned invalid JSON") from exc

    if res.status_code >= 400:
        raise HTTPException(status_code=res.status_code, detail=payload.get("status_message", "Upstream error"))

    return JSONResponse(content=payload, status_code=res.status_code)


@app.get(f"{API_PREFIX}/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "upstream": UPSTREAM}


@app.get(f"{API_PREFIX}/{{path}}")
async def yts_proxy(path: str, request: Request) -> JSONResponse:
    if path not in PROXY_PATHS:
        raise HTTPException(status_code=404, detail=f"Unknown endpoint: {path}")

    params = dict(request.query_params)
    return await proxy_yts(path, params)
