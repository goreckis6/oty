import json
import os
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).resolve().parent / "data" / "test_movies.json"
DATA_SOURCE = os.environ.get("DATA_SOURCE", "scrape").lower()


def _load() -> dict[str, Any]:
    if not DATA_FILE.exists():
        raise FileNotFoundError(
            f"Brak {DATA_FILE}. Uruchom: python scrape_yts.py"
        )
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _match_genre(movie: dict[str, Any], genre: str) -> bool:
    if genre == "All":
        return True
    return genre in (movie.get("genres") or [])


def _match_query(movie: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    q = query.lower()
    hay = " ".join(
        [
            movie.get("title") or "",
            movie.get("title_english") or "",
            movie.get("imdb_code") or "",
        ]
    ).lower()
    return q in hay


def _match_rating(movie: dict[str, Any], minimum: float) -> bool:
    return float(movie.get("rating") or 0) >= minimum


def _match_quality(movie: dict[str, Any], quality: str) -> bool:
    if quality == "All":
        return True
    torrents = movie.get("torrents") or []
    return any((t.get("quality") or "").lower() == quality.lower() for t in torrents)


def _sort_movies(movies: list[dict], sort_by: str, order: str) -> list[dict]:
    reverse = order != "asc"

    def key(m: dict) -> Any:
        if sort_by == "title":
            return (m.get("title") or "").lower()
        if sort_by == "year":
            return m.get("year") or 0
        if sort_by == "rating":
            return m.get("rating") or 0
        if sort_by == "like_count":
            return m.get("like_count") or 0
        if sort_by == "download_count":
            return m.get("download_count") or 0
        if sort_by == "seeds":
            ts = m.get("torrents") or []
            return max((t.get("seeds") or 0) for t in ts) if ts else 0
        return m.get("date_uploaded_unix") or 0

    return sorted(movies, key=key, reverse=reverse)


class ScrapeCache:
    def __init__(self) -> None:
        self._cache = _load()

    def reload(self) -> None:
        self._cache = _load()

    @property
    def movies(self) -> list[dict[str, Any]]:
        return self._cache.get("movies") or []

    def list_movies(self, params: dict[str, Any]) -> dict[str, Any]:
        page = int(params.get("page") or 1)
        limit = min(int(params.get("limit") or 20), 50)
        query = (params.get("query_term") or "").strip()
        genre = params.get("genre") or "All"
        min_rating = float(params.get("minimum_rating") or 0)
        quality = params.get("quality") or "All"
        sort_by = params.get("sort_by") or "date_added"
        order = params.get("order_by") or "desc"

        filtered = [
            m
            for m in self.movies
            if _match_genre(m, genre)
            and _match_query(m, query)
            and _match_rating(m, min_rating)
            and _match_quality(m, quality)
        ]
        filtered = _sort_movies(filtered, sort_by, order)

        start = (page - 1) * limit
        page_items = filtered[start : start + limit]

        summaries = [
            {
                k: m.get(k)
                for k in (
                    "id",
                    "imdb_code",
                    "title",
                    "title_english",
                    "title_long",
                    "slug",
                    "year",
                    "rating",
                    "runtime",
                    "genres",
                    "summary",
                    "medium_cover_image",
                    "small_cover_image",
                    "large_cover_image",
                )
            }
            for m in page_items
        ]

        return {
            "movie_count": len(filtered),
            "limit": limit,
            "page_number": page,
            "movies": summaries,
        }

    def movie_details(
        self, movie_id: int | None = None, slug: str | None = None
    ) -> dict[str, Any]:
        for m in self.movies:
            if movie_id is not None and m.get("id") == movie_id:
                return {"movie": m}
            if slug and (m.get("slug") or "").lower() == slug.lower():
                return {"movie": m}
        raise KeyError(f"Movie not found: id={movie_id} slug={slug}")

    def list_upcoming(self) -> dict[str, Any]:
        upcoming = self._cache.get("upcoming") or self.movies[:4]
        return {"movies": upcoming[:8]}

    def movie_suggestions(
        self, movie_id: int | None = None, slug: str | None = None
    ) -> dict[str, Any]:
        target = None
        for m in self.movies:
            if movie_id is not None and m.get("id") == movie_id:
                target = m
                break
            if slug and (m.get("slug") or "").lower() == slug.lower():
                target = m
                break
        if not target:
            return {"movies": self._summaries(self.movies[:4])}

        mid = target.get("id")
        genres = set(target.get("genres") or [])
        similar = [
            m
            for m in self.movies
            if m.get("id") != mid and genres.intersection(m.get("genres") or [])
        ]
        if not similar:
            similar = [m for m in self.movies if m.get("id") != mid]
        return {"movies": self._summaries(similar[:4])}

    def _summaries(self, movies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        keys = (
            "id", "imdb_code", "title", "title_english", "title_long", "slug",
            "year", "rating", "runtime", "genres", "summary",
            "medium_cover_image", "small_cover_image", "large_cover_image",
        )
        return [{k: m.get(k) for k in keys} for m in movies]
