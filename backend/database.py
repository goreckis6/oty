import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(os.environ.get("DB_PATH", str(Path(__file__).resolve().parent / "data" / "movies.db")))

# Legacy seed IDs from old test_movies.json — removed on first startup after upgrade.
LEGACY_SEED_MOVIE_IDS = frozenset({
    76899, 76898, 76897, 76896, 76891, 76890, 76889, 76888, 76887, 76886,
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    t = re.sub(r"\s+", " ", title.lower().strip())
    return t


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._remove_legacy_seed_movies()
        self.prune_upcoming()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS movies (
                    id INTEGER PRIMARY KEY,
                    slug TEXT UNIQUE NOT NULL,
                    title TEXT,
                    year INTEGER,
                    rating REAL,
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_movies_slug ON movies(slug);
                CREATE INDEX IF NOT EXISTS idx_movies_year ON movies(year);
                CREATE INDEX IF NOT EXISTS idx_movies_rating ON movies(rating);

                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def _remove_legacy_seed_movies(self) -> None:
        if self.get_meta("legacy_seed_removed", "0") == "1":
            return
        removed = 0
        for movie_id in LEGACY_SEED_MOVIE_IDS:
            if self.delete_movie(movie_id):
                removed += 1
        self.set_meta("legacy_seed_removed", "1")
        self.prune_upcoming()

    def _upcoming_in_db(self, movie: dict[str, Any], existing_ids: set[int]) -> bool:
        movie_id = int(movie.get("id") or 0)
        if movie_id and movie_id in existing_ids:
            return True
        slug = (movie.get("slug") or "").strip()
        return bool(slug and self.get_movie(slug=slug))

    def prune_upcoming(self) -> int:
        upcoming = self.get_upcoming()
        if not upcoming:
            return 0
        existing_ids = self.existing_ids()
        pruned = [m for m in upcoming if self._upcoming_in_db(m, existing_ids)]
        removed = len(upcoming) - len(pruned)
        if removed:
            self.set_upcoming(pruned)
        return removed

    def count_movies(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM movies").fetchone()
            return int(row["c"])

    def existing_ids(self) -> set[int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT id FROM movies").fetchall()
        return {int(r["id"]) for r in rows}

    def existing_titles(self) -> set[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT title FROM movies WHERE title IS NOT NULL").fetchall()
        return {normalize_title(r["title"]) for r in rows if normalize_title(r["title"])}

    def duplicate_title_keys(self) -> set[str]:
        counts: dict[str, int] = {}
        with self.connect() as conn:
            rows = conn.execute("SELECT title FROM movies WHERE title IS NOT NULL").fetchall()
        for row in rows:
            key = normalize_title(row["title"])
            if key:
                counts[key] = counts.get(key, 0) + 1
        return {key for key, count in counts.items() if count > 1}

    def upsert_movie(self, movie: dict[str, Any]) -> None:
        mid = int(movie["id"])
        slug = movie.get("slug") or f"movie-{mid}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO movies (id, slug, title, year, rating, data, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    slug=excluded.slug,
                    title=excluded.title,
                    year=excluded.year,
                    rating=excluded.rating,
                    data=excluded.data,
                    updated_at=excluded.updated_at
                """,
                (
                    mid,
                    slug,
                    movie.get("title"),
                    movie.get("year"),
                    movie.get("rating"),
                    json.dumps(movie, ensure_ascii=False),
                    _now(),
                ),
            )

    def upsert_movies(self, movies: list[dict[str, Any]]) -> int:
        for m in movies:
            self.upsert_movie(m)
        return len(movies)

    def all_movies(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT data FROM movies ORDER BY id DESC").fetchall()
        return [json.loads(r["data"]) for r in rows]

    def get_movie(self, movie_id: int | None = None, slug: str | None = None) -> dict[str, Any] | None:
        with self.connect() as conn:
            if movie_id is not None:
                row = conn.execute("SELECT data FROM movies WHERE id = ?", (movie_id,)).fetchone()
            elif slug:
                row = conn.execute(
                    "SELECT data FROM movies WHERE lower(slug) = lower(?)", (slug,)
                ).fetchone()
            else:
                return None
        return json.loads(row["data"]) if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_meta(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def get_upcoming(self) -> list[dict[str, Any]]:
        raw = self.get_meta("upcoming", "[]")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []

    def set_upcoming(self, movies: list[dict[str, Any]]) -> None:
        self.set_meta("upcoming", json.dumps(movies, ensure_ascii=False))

    def get_last_batch_ids(self) -> set[int]:
        raw = self.get_meta("last_batch_ids", "[]")
        try:
            return {int(x) for x in json.loads(raw)}
        except (json.JSONDecodeError, TypeError, ValueError):
            return set()

    def set_last_batch_ids(self, ids: list[int]) -> None:
        self.set_meta("last_batch_ids", json.dumps(ids))

    def list_rows(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, slug, title, year, rating, updated_at FROM movies ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def list_rows_paginated(self, page: int = 1, limit: int = 100) -> tuple[list[dict[str, Any]], int]:
        page = max(1, page)
        limit = max(1, limit)
        offset = (page - 1) * limit
        with self.connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) AS c FROM movies").fetchone()["c"])
            rows = conn.execute(
                """
                SELECT id, slug, title, year, rating, updated_at
                FROM movies ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows], total

    def list_sitemap_entries(self) -> list[dict[str, Any]]:
        return [
            {"slug": row["slug"], "updated_at": row["updated_at"]}
            for row in self.list_rows()
            if row.get("slug")
        ]

    def delete_movie(self, movie_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM movies WHERE id = ?", (movie_id,))
            deleted = cur.rowcount > 0
        if not deleted:
            return False

        current_batch = list(self.get_last_batch_ids())
        if movie_id in current_batch:
            self.set_last_batch_ids([i for i in current_batch if i != movie_id])

        upcoming = self.get_upcoming()
        if upcoming:
            filtered = [m for m in upcoming if int(m.get("id") or 0) != movie_id]
            if len(filtered) != len(upcoming):
                self.set_upcoming(filtered)
        return True

    def delete_movies(self, movie_ids: list[int]) -> int:
        deleted = 0
        for movie_id in movie_ids:
            if self.delete_movie(int(movie_id)):
                deleted += 1
        return deleted

    def delete_all_movies(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM movies")
