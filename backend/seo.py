import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from movie_enrichment import plot_synopsis


def normalize_site_url(url: str) -> str:
    return url.strip().rstrip("/")


PUBLIC_DIR = Path(os.environ.get("PUBLIC_DIR", "/app/public"))
SITE_URL = normalize_site_url(os.environ.get("SITE_URL", "http://localhost"))
SITE_NAME = os.environ.get("SITE_NAME", "YTS")
SITE_TAGLINE = os.environ.get("SITE_TAGLINE", "HD movies at the smallest file size")
SITEMAP_MAX_URLS = 200

_INDEX_TEMPLATE: str | None = None


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _clean_text(value: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def movie_page_title(movie: dict[str, Any]) -> str:
    title = movie.get("title") or "Movie"
    year = movie.get("year") or ""
    return f"{title} ({year}) YIFY Torrent Download — {SITE_NAME}"


def movie_description(movie: dict[str, Any]) -> str:
    summary = plot_synopsis(movie)
    label = movie.get("title_long") or movie.get("title") or "Movie"
    base = f"Download {label} YIFY HD torrent in 720p, 1080p and x265."
    if summary:
        return _clean_text(f"{base} {summary}", 300)
    return base


def movie_canonical(slug: str) -> str:
    return f"{SITE_URL}/movies/{slug}"


def movie_og_image(movie: dict[str, Any]) -> str:
    return (
        movie.get("large_cover_image")
        or movie.get("medium_cover_image")
        or movie.get("small_cover_image")
        or f"{SITE_URL}/favicon.ico"
    )


def movie_json_ld(movie: dict[str, Any], canonical: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Movie",
        "name": movie.get("title") or "Movie",
        "description": movie_description(movie),
        "image": movie_og_image(movie),
        "url": canonical,
        "mainEntityOfPage": canonical,
    }
    if movie.get("year"):
        payload["datePublished"] = str(movie["year"])
    if movie.get("imdb_code"):
        payload["sameAs"] = f"https://www.imdb.com/title/{movie['imdb_code']}/"
    rating = movie.get("rating")
    if rating:
        payload["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": float(rating),
            "bestRating": 10,
            "worstRating": 0,
            "ratingCount": max(int(movie.get("like_count") or 0), 1),
        }
    genres = movie.get("genres") or []
    if genres:
        payload["genre"] = genres
    return payload


def format_lastmod(value: str | None = None) -> str:
    if not value:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except ValueError:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def movie_slug(movie: dict[str, Any]) -> str:
    return str(movie.get("slug") or f"movie-{movie.get('id')}")


def movie_seo_url(movie: dict[str, Any]) -> str:
    return movie_canonical(movie_slug(movie))


def movie_seo_urls(movies: list[dict[str, Any]]) -> list[str]:
    return [movie_seo_url(m) for m in movies if m.get("slug") or m.get("id")]


def build_head_injection(
    *,
    page_type: str = "home",
    movie: dict[str, Any] | None = None,
    title: str | None = None,
    description: str | None = None,
    canonical: str | None = None,
    image: str | None = None,
    robots: str = "index,follow",
    json_ld: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> str:
    if page_type == "movie" and movie:
        title = movie_page_title(movie)
        description = movie_description(movie)
        canonical = movie_canonical(movie_slug(movie))
        image = movie_og_image(movie)
        json_ld = movie_json_ld(movie, canonical)
    else:
        title = title or f"{SITE_NAME} — YIFY Movies"
        description = description or (
            f"Browse and download YIFY movies in HD quality at the smallest file size. {SITE_TAGLINE}"
        )
        canonical = canonical or SITE_URL + "/"
        image = image or f"{SITE_URL}/favicon.ico"

    tags = [
        f'<title>{_esc(title)}</title>',
        f'<meta name="description" content="{_esc(description)}" />',
        f'<meta name="robots" content="{_esc(robots)}" />',
        f'<link rel="canonical" href="{_esc(canonical)}" />',
        f'<link rel="sitemap" type="application/xml" title="Sitemap" href="{_esc(SITE_URL)}/sitemap.xml" />',
        f'<meta property="og:type" content="{"video.movie" if page_type == "movie" else "website"}" />',
        f'<meta property="og:site_name" content="{_esc(SITE_NAME)}" />',
        f'<meta property="og:title" content="{_esc(title)}" />',
        f'<meta property="og:description" content="{_esc(description)}" />',
        f'<meta property="og:url" content="{_esc(canonical)}" />',
        f'<meta property="og:image" content="{_esc(image)}" />',
        f'<meta name="twitter:card" content="summary_large_image" />',
        f'<meta name="twitter:title" content="{_esc(title)}" />',
        f'<meta name="twitter:description" content="{_esc(description)}" />',
        f'<meta name="twitter:image" content="{_esc(image)}" />',
    ]
    if json_ld:
        tags.append(
            '<script type="application/ld+json">'
            + json.dumps(json_ld, ensure_ascii=False)
            + "</script>"
        )
    return "\n  ".join(tags)


def build_movie_prerender(movie: dict[str, Any]) -> str:
    title = movie.get("title") or "Movie"
    year = movie.get("year") or ""
    slug = movie_slug(movie)
    summary = _clean_text(
        plot_synopsis(movie) or "No description available.",
        500,
    )
    poster = movie.get("large_cover_image") or movie.get("medium_cover_image") or ""
    genres = ", ".join(movie.get("genres") or [])
    rating = movie.get("rating")
    rating_text = f"IMDb rating: {rating:.1f}/10. " if rating else ""

    return f"""
    <article class="seo-prerender">
      <h1>{_esc(title)} ({_esc(year)}) — YIFY HD Torrent</h1>
      {f'<img src="{_esc(poster)}" alt="{_esc(title)} poster" width="300" />' if poster else ""}
      <p>{rating_text}{_esc(summary)}</p>
      {f'<p>Genres: {_esc(genres)}</p>' if genres else ""}
      <p><a href="{_esc(movie_canonical(slug))}">View {_esc(title)} on {_esc(SITE_NAME)}</a></p>
    </article>"""


def load_index_template() -> str:
    global _INDEX_TEMPLATE
    if _INDEX_TEMPLATE is None:
        path = PUBLIC_DIR / "index.html"
        _INDEX_TEMPLATE = path.read_text(encoding="utf-8")
    return _INDEX_TEMPLATE


def inject_head(html_doc: str, head_html: str) -> str:
    return re.sub(
        r"<!-- SEO_START -->[\s\S]*?<!-- SEO_END -->",
        f"<!-- SEO_START -->\n  {head_html}\n  <!-- SEO_END -->",
        html_doc,
        count=1,
    )


def render_movie_page(movie: dict[str, Any]) -> str:
    tpl = load_index_template()
    head = build_head_injection(page_type="movie", movie=movie)
    body = build_movie_prerender(movie)
    out = inject_head(tpl, head)
    out = re.sub(
        r'(<main class="main" id="app">)[\s\S]*?(</main>)',
        rf"\1{body}\2",
        out,
        count=1,
    )
    return out


def collect_sitemap_urls(entries: list[dict[str, Any]] | None = None) -> list[tuple[str, str, str]]:
    """Return (loc, lastmod, priority) tuples for all indexable pages."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls: list[tuple[str, str, str]] = [
        (f"{SITE_URL}/", today, "1.0"),
        (f"{SITE_URL}/browse", today, "0.9"),
    ]
    for entry in entries or []:
        slug = entry.get("slug")
        if not slug:
            continue
        lastmod = format_lastmod(entry.get("updated_at"))
        urls.append((movie_canonical(slug), lastmod, "0.8"))
    return urls


def chunk_sitemap_urls(urls: list[tuple[str, str, str]], size: int = SITEMAP_MAX_URLS) -> list[list[tuple[str, str, str]]]:
    if not urls:
        return [[]]
    return [urls[i : i + size] for i in range(0, len(urls), size)]


def build_sitemap_urlset(urls: list[tuple[str, str, str]]) -> str:
    urlset = Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for loc, lastmod, priority in urls:
        node = SubElement(urlset, "url")
        SubElement(node, "loc").text = loc
        SubElement(node, "lastmod").text = lastmod
        SubElement(node, "changefreq").text = "weekly"
        SubElement(node, "priority").text = priority
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(urlset, encoding="unicode")


def build_sitemap_index(chunk_count: int) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    root = Element("sitemapindex", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for index in range(1, chunk_count + 1):
        node = SubElement(root, "sitemap")
        SubElement(node, "loc").text = f"{SITE_URL}/sitemap{index}.xml"
        SubElement(node, "lastmod").text = today
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="unicode")


def sitemap_chunks(entries: list[dict[str, Any]] | None = None) -> list[list[tuple[str, str, str]]]:
    return chunk_sitemap_urls(collect_sitemap_urls(entries))


def build_sitemap(entries: list[dict[str, Any]] | None = None) -> str:
    """Root sitemap: urlset when <=200 URLs, otherwise a sitemap index."""
    chunks = sitemap_chunks(entries)
    if len(chunks) <= 1 and len(chunks[0]) <= SITEMAP_MAX_URLS:
        return build_sitemap_urlset(chunks[0])
    return build_sitemap_index(len(chunks))


def build_sitemap_part(entries: list[dict[str, Any]] | None, index: int) -> str | None:
    chunks = sitemap_chunks(entries)
    if index < 1 or index > len(chunks):
        return None
    if len(chunks) == 1 and len(chunks[0]) <= SITEMAP_MAX_URLS:
        return None
    return build_sitemap_urlset(chunks[index - 1])


def register_movies_for_seo(db: Any, movies: list[dict[str, Any]]) -> list[str]:
    """Mark freshly stored movies as sitemap-ready. SEO pages are generated on demand."""
    urls = movie_seo_urls(movies)
    if urls:
        db.set_meta("seo_last_update", datetime.now(timezone.utc).isoformat())
        db.set_meta("seo_url_count", str(len(db.list_sitemap_entries())))
    return urls


def build_robots() -> str:
    return f"""User-agent: *
Allow: /
Disallow: /twojastara
Disallow: /api/v1/admin/

Sitemap: {SITE_URL}/sitemap.xml
"""
