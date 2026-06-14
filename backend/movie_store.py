import os
from typing import Any

from database import Database, normalize_title

SUMMARY_KEYS = (
    "id", "imdb_code", "title", "title_english", "title_long", "slug",
    "year", "rating", "runtime", "genres", "summary",
    "medium_cover_image", "small_cover_image", "large_cover_image",
)


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
            movie.get("slug") or "",
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


def _summaries(movies: list[dict[str, Any]], new_ids: set[int] | None = None) -> list[dict[str, Any]]:
    new_ids = new_ids or set()
    result = []
    for m in movies:
        item = {k: m.get(k) for k in SUMMARY_KEYS}
        item["is_new"] = int(m.get("id") or 0) in new_ids
        result.append(item)
    return result


class MovieStore:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    @property
    def new_ids(self) -> set[int]:
        return self.db.get_last_batch_ids()

    def _tag_new(self, movie: dict[str, Any]) -> dict[str, Any]:
        movie = dict(movie)
        movie["is_new"] = int(movie.get("id") or 0) in self.new_ids
        return movie

    @property
    def movies(self) -> list[dict[str, Any]]:
        return self.db.all_movies()

    def list_all_admin(self) -> list[dict[str, Any]]:
        new_ids = self.new_ids
        duplicate_titles = self.db.duplicate_title_keys()
        items = []
        for row in self.db.list_rows():
            title_key = normalize_title(row.get("title"))
            items.append({
                **row,
                "is_new": int(row["id"]) in new_ids,
                "is_duplicate_title": bool(title_key and title_key in duplicate_titles),
                "url": f"/movies/{row['slug']}",
            })
        return items

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

        return {
            "movie_count": len(filtered),
            "limit": limit,
            "page_number": page,
            "movies": _summaries(page_items, self.new_ids),
        }

    def movie_details(
        self, movie_id: int | None = None, slug: str | None = None
    ) -> dict[str, Any]:
        movie = self.db.get_movie(movie_id=movie_id, slug=slug)
        if not movie:
            raise KeyError(f"Movie not found: id={movie_id} slug={slug}")
        return {"movie": self._tag_new(movie)}

    def list_upcoming(self) -> dict[str, Any]:
        upcoming = self.db.get_upcoming()
        if not upcoming:
            upcoming = _summaries(self.movies[:4], self.new_ids)
        else:
            upcoming = _summaries(upcoming, self.new_ids)
        return {"movies": upcoming[:8]}

    def movie_suggestions(
        self, movie_id: int | None = None, slug: str | None = None
    ) -> dict[str, Any]:
        target = self.db.get_movie(movie_id=movie_id, slug=slug)
        if not target:
            return {"movies": _summaries(self.movies[:4], self.new_ids)}

        mid = target.get("id")
        genres = set(target.get("genres") or [])
        similar = [
            m
            for m in self.movies
            if m.get("id") != mid and genres.intersection(m.get("genres") or [])
        ]
        if not similar:
            similar = [m for m in self.movies if m.get("id") != mid]
        return {"movies": _summaries(similar[:4], self.new_ids)}
