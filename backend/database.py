import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(os.environ.get("DB_PATH", str(Path(__file__).resolve().parent / "data" / "movies.db")))
JSON_FALLBACK = Path(__file__).resolve().parent / "data" / "test_movies.json"


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
        self._import_json_if_empty()

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

    def _import_json_if_empty(self) -> None:
        if self.count_movies() > 0 or not JSON_FALLBACK.exists():
            return
        payload = json.loads(JSON_FALLBACK.read_text(encoding="utf-8"))
        for movie in payload.get("movies") or []:
            self.upsert_movie(movie)
        upcoming = payload.get("upcoming") or []
        if upcoming:
            self.set_meta("upcoming", json.dumps(upcoming))

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

    def delete_all_movies(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM movies")
