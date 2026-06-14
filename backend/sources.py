import os
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

TMDB_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_BASE = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p"

TORRENT_SOURCE = os.environ.get("TORRENT_SOURCE", "apibay").lower()
APIBAY_URL = os.environ.get("APIBAY_URL", "https://apibay.org").rstrip("/")
TORZNAB_URL = os.environ.get("TORZNAB_URL", "").rstrip("/")
TORZNAB_API_KEY = os.environ.get("TORZNAB_API_KEY", "")
DATA_SOURCE = os.environ.get("DATA_SOURCE", "sqlite").lower()

GENRES: dict[str, int] = {
    "Action": 28,
    "Adventure": 12,
    "Animation": 16,
    "Biography": 99,
    "Comedy": 35,
    "Crime": 80,
    "Documentary": 99,
    "Drama": 18,
    "Family": 10751,
    "Fantasy": 14,
    "History": 36,
    "Horror": 27,
    "Music": 10402,
    "Mystery": 9648,
    "Romance": 10749,
    "Sci-Fi": 878,
    "Sport": 10752,
    "Thriller": 53,
    "War": 10752,
    "Western": 37,
}

GENRE_BY_ID = {
    28: "Action",
    12: "Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    18: "Drama",
    10751: "Family",
    14: "Fantasy",
    36: "History",
    27: "Horror",
    10402: "Music",
    9648: "Mystery",
    10749: "Romance",
    878: "Sci-Fi",
    10752: "Sport",
    53: "Thriller",
    37: "Western",
    99: "Documentary",
}

SORT_MAP = {
    "date_added": "primary_release_date.desc",
    "year": "primary_release_date.desc",
    "rating": "vote_average.desc",
    "like_count": "popularity.desc",
    "download_count": "popularity.desc",
    "title": "original_title.asc",
    "seeds": "popularity.desc",
}

QUALITY_RE = re.compile(r"\b(480p|720p|1080p|1080p\.x265|2160p|4k|3d)\b", re.I)


def ok(data: Any, message: str = "Query was successful", source: str = "tmdb") -> dict[str, Any]:
    return {
        "status": "ok",
        "status_message": message,
        "data": data,
        "@meta": {"api_version": 1, "source": source},
    }


def slugify(title: str, year: int | str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{s}-{year}"


def poster(path: str | None, size: str = "w500") -> str:
    return f"{IMG_BASE}/{size}{path}" if path else ""


def parse_quality(name: str) -> str:
    m = QUALITY_RE.search(name)
    if not m:
        return "720p"
    q = m.group(1).lower()
    return "2160p" if q == "4k" else q


def fmt_size(num_bytes: int) -> str:
    if num_bytes >= 1_073_741_824:
        return f"{num_bytes / 1_073_741_824:.2f} GB"
    if num_bytes >= 1_048_576:
        return f"{num_bytes / 1_048_576:.1f} MB"
    return f"{num_bytes} B"


def build_magnet(info_hash: str, name: str) -> str:
    return f"magnet:?xt=urn:btih:{info_hash}&dn={name}"


class TmdbClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=25.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        q = {"api_key": self.api_key, "language": "en-US"}
        if params:
            q.update(params)
        res = await self._client.get(f"{TMDB_BASE}{path}", params=q)
        res.raise_for_status()
        return res.json()

    async def list_movies(self, params: dict[str, Any]) -> dict[str, Any]:
        page = int(params.get("page") or 1)
        limit = min(int(params.get("limit") or 20), 50)
        query = (params.get("query_term") or "").strip()
        genre = params.get("genre") or "All"
        min_rating = float(params.get("minimum_rating") or 0)
        sort_by = SORT_MAP.get(params.get("sort_by") or "date_added", "popularity.desc")

        if query:
            data = await self._get(
                "/search/movie",
                {"query": query, "page": page, "include_adult": "false"},
            )
        else:
            discover: dict[str, Any] = {
                "page": page,
                "sort_by": sort_by,
                "include_adult": "false",
                "include_video": "false",
                "vote_count.gte": 50,
            }
            if genre != "All" and genre in GENRES:
                discover["with_genres"] = GENRES[genre]
            if min_rating > 0:
                discover["vote_average.gte"] = min_rating
            data = await self._get("/discover/movie", discover)

        movies = [movie_summary(m) for m in data.get("results", [])]
        if params.get("quality") and params["quality"] != "All":
            # Quality filter applies to torrents; keep list, filter on details
            pass

        total = data.get("total_results", len(movies))
        return {
            "movie_count": total,
            "limit": limit,
            "page_number": page,
            "movies": movies[:limit],
        }

    async def movie_details(self, movie_id: int) -> dict[str, Any]:
        movie = await self._get(f"/movie/{movie_id}")
        videos = await self._get(f"/movie/{movie_id}/videos")
        trailer = next(
            (v["key"] for v in videos.get("results", []) if v.get("site") == "YouTube" and v.get("type") == "Trailer"),
            "",
        )
        return {"movie": movie_full(movie, trailer)}

    async def list_upcoming(self) -> dict[str, Any]:
        data = await self._get("/movie/upcoming", {"page": 1})
        return {"movies": [movie_summary(m) for m in data.get("results", [])[:8]]}

    async def movie_suggestions(self, movie_id: int) -> dict[str, Any]:
        data = await self._get(f"/movie/{movie_id}/similar", {"page": 1})
        return {"movies": [movie_summary(m) for m in data.get("results", [])[:4]]}


def movie_summary(m: dict[str, Any]) -> dict[str, Any]:
    year = (m.get("release_date") or "0000")[:4]
    genres = [GENRE_BY_ID[g] for g in (m.get("genre_ids") or []) if g in GENRE_BY_ID][:3]
    if not genres and m.get("genres"):
        genres = [g["name"] for g in m["genres"][:3]]
    title = m.get("title") or m.get("name") or "Unknown"
    y = int(year) if year.isdigit() else 0
    return {
        "id": m["id"],
        "imdb_code": "",
        "title": title,
        "title_english": title,
        "title_long": f"{title} ({y})" if y else title,
        "slug": slugify(title, y),
        "year": y,
        "rating": round(float(m.get("vote_average") or 0), 1),
        "runtime": 0,
        "genres": genres,
        "summary": m.get("overview") or "",
        "medium_cover_image": poster(m.get("poster_path")),
        "small_cover_image": poster(m.get("poster_path"), "w342"),
        "large_cover_image": poster(m.get("poster_path"), "w780"),
    }


def movie_full(m: dict[str, Any], trailer: str = "") -> dict[str, Any]:
    base = movie_summary(m)
    year = base["year"]
    title = base["title"]
    base.update(
        {
            "runtime": m.get("runtime") or 0,
            "language": (m.get("original_language") or "en").upper(),
            "mpa_rating": "",
            "description_intro": m.get("overview") or "",
            "description_full": m.get("overview") or "",
            "background_image": poster(m.get("backdrop_path"), "w1280"),
            "background_image_original": poster(m.get("backdrop_path"), "original"),
            "yt_trailer_code": trailer,
            "like_count": int(m.get("vote_count") or 0),
            "download_count": int((m.get("popularity") or 0) * 100),
            "torrents": [],
        }
    )
    return base


class TorrentSearch:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=20.0, follow_redirects=True)

    async def close(self) -> None:
        await self._client.aclose()

    async def search(self, title: str, year: int, quality_filter: str | None = None) -> list[dict[str, Any]]:
        if TORRENT_SOURCE == "none":
            return []
        if TORRENT_SOURCE == "torznab" and TORZNAB_URL:
            return await self._torznab(title, year, quality_filter)
        return await self._apibay(title, year, quality_filter)

    async def _apibay(self, title: str, year: int, quality_filter: str | None) -> list[dict[str, Any]]:
        queries = [
            f"{title} {year} YIFY",
            f"{title} {year} 1080p",
            f"{title} {year}",
        ]
        items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for q in queries:
            res = await self._client.get(f"{APIBAY_URL}/q.php", params={"q": q, "cat": "201"})
            if res.status_code != 200:
                continue
            try:
                batch = res.json()
            except ValueError:
                continue
            if not isinstance(batch, list):
                continue
            for item in batch:
                iid = str(item.get("id", ""))
                if iid and iid not in seen_ids:
                    seen_ids.add(iid)
                    items.append(item)
            if len(items) >= 20:
                break

        torrents: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or ""
            info_hash = (item.get("info_hash") or "").strip()
            if not info_hash or info_hash == "0" * 40:
                continue
            quality = parse_quality(name)
            if quality_filter and quality_filter != "All" and quality != quality_filter.lower():
                continue
            key = f"{quality}:{info_hash}"
            if key in seen:
                continue
            seen.add(key)
            size_bytes = int(item.get("size") or 0)
            torrents.append(
                {
                    "url": f"https://thepiratebay.org/description.php?id={item.get('id', '')}",
                    "hash": info_hash,
                    "quality": quality,
                    "type": "web",
                    "seeds": int(item.get("seeders") or 0),
                    "peers": int(item.get("leechers") or 0),
                    "size": fmt_size(size_bytes),
                    "size_bytes": size_bytes,
                    "magnet_url": build_magnet(info_hash, name),
                    "date_uploaded": "",
                    "date_uploaded_unix": 0,
                }
            )
        torrents.sort(key=lambda t: (t["seeds"], t["size_bytes"]), reverse=True)
        return torrents[:6]

    async def _torznab(self, title: str, year: int, quality_filter: str | None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "t": "search",
            "q": f"{title} {year}",
            "cat": "2000,2040,2045,2060",
        }
        if TORZNAB_API_KEY:
            params["apikey"] = TORZNAB_API_KEY
        res = await self._client.get(f"{TORZNAB_URL}/api", params=params)
        if res.status_code != 200:
            return []

        try:
            root = ET.fromstring(res.text)
        except ET.ParseError:
            return []

        ns = {"torznab": "http://torznab.com/schemas/2015/feed"}
        torrents: list[dict[str, Any]] = []
        for item in root.findall(".//item"):
            title_el = item.find("title")
            name = title_el.text if title_el is not None and title_el.text else ""
            quality = parse_quality(name)
            if quality_filter and quality_filter != "All" and quality != quality_filter.lower():
                continue
            enclosure = item.find("enclosure")
            magnet = enclosure.get("url", "") if enclosure is not None else ""
            info_hash = ""
            for attr in item.findall("torznab:attr", ns):
                if attr.get("name") == "infohash":
                    info_hash = attr.get("value", "")
            size_bytes = 0
            for attr in item.findall("torznab:attr", ns):
                if attr.get("name") == "size":
                    size_bytes = int(attr.get("value") or 0)
            seeds = 0
            peers = 0
            for attr in item.findall("torznab:attr", ns):
                if attr.get("name") == "seeders":
                    seeds = int(attr.get("value") or 0)
                if attr.get("name") == "peers":
                    peers = int(attr.get("value") or 0)
            if not magnet and info_hash:
                magnet = build_magnet(info_hash, name)
            torrents.append(
                {
                    "url": magnet,
                    "hash": info_hash,
                    "quality": quality,
                    "type": "web",
                    "seeds": seeds,
                    "peers": peers,
                    "size": fmt_size(size_bytes),
                    "size_bytes": size_bytes,
                    "magnet_url": magnet,
                    "date_uploaded": "",
                    "date_uploaded_unix": 0,
                }
            )
        return torrents[:6]
