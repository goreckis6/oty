(function () {
  const cfg = () => window.YTS_CONFIG || {};
  const siteUrl = () => (cfg().siteUrl || window.location.origin).replace(/\/$/, "");
  const siteName = () => cfg().siteName || "YTS";
  const tagline = () => cfg().siteTagline || "HD movies at the smallest file size";

  function upsertMeta(attr, key, content) {
    if (!content) return;
    let el = document.querySelector(`meta[${attr}="${key}"]`);
    if (!el) {
      el = document.createElement("meta");
      el.setAttribute(attr, key);
      document.head.appendChild(el);
    }
    el.setAttribute("content", content);
  }

  function upsertLink(rel, href) {
    if (!href) return;
    let el = document.querySelector(`link[rel="${rel}"]`);
    if (!el) {
      el = document.createElement("link");
      el.setAttribute("rel", rel);
      document.head.appendChild(el);
    }
    el.setAttribute("href", href);
  }

  function upsertJsonLd(data) {
    let el = document.getElementById("seo-jsonld");
    if (!data) {
      if (el) el.remove();
      return;
    }
    if (!el) {
      el = document.createElement("script");
      el.type = "application/ld+json";
      el.id = "seo-jsonld";
      document.head.appendChild(el);
    }
    el.textContent = JSON.stringify(data);
  }

  function cleanText(text, limit) {
    const value = String(text || "").replace(/\s+/g, " ").trim();
    if (value.length <= limit) return value;
    return value.slice(0, limit - 3).trim() + "...";
  }

  function homeTitle() {
    return `${siteName()}: The Official Home of YIFY Movies Download`;
  }

  function homeDescription() {
    const name = siteName();
    return cleanText(
      `${name} YIFY movies download — official YIFY and YTS movies site. ` +
        "Free YIFY films, HD downloads in 720p, 1080p, 1080p x265, 2160p 4K Ultra HD, 3D BluRay and WEBRip. " +
        "Download smallest file size YIFY releases with magnet links and subtitles. " +
        "Browse latest YIFY catalog, HD movie downloads, new releases by genre.",
      320
    );
  }

  function homeJsonLd() {
    const name = siteName();
    return {
      "@context": "https://schema.org",
      "@type": "WebSite",
      name,
      alternateName: `${name} YIFY Movies`,
      url: `${siteUrl()}/`,
      description: tagline(),
      potentialAction: {
        "@type": "SearchAction",
        target: `${siteUrl()}/browse?q={search_term_string}`,
        "query-input": "required name=search_term_string",
      },
    };
  }

  function movieDescription(movie) {
    const title = movie.title || "Movie";
    const year = movie.year;
    const label = movie.title_long || (year ? `${title} (${year})` : title);
    const name = siteName();
    const parts = [
      `Download ${label} YIFY movie in 720p, 1080p, 2160p 4K and x265.`,
    ];

    if (movie.rating) {
      parts.push(`IMDb ${Number(movie.rating).toFixed(1)}/10.`);
    }

    const genres = movie.genres || [];
    if (genres.length) {
      parts.push(`${genres.slice(0, 4).join(", ")}.`);
    }

    const summary =
      movie.plot_summary || movie.synopsis || movie.description_full || movie.description_intro || movie.summary || "";
    if (summary) {
      parts.push(summary);
    }

    parts.push(`Watch and download on ${name}.`);
    return cleanText(parts.join(" "), 300);
  }

  function movieJsonLd(movie, canonical) {
    const payload = {
      "@context": "https://schema.org",
      "@type": "Movie",
      name: movie.title || "Movie",
      description: movieDescription(movie),
      image:
        movie.large_cover_image ||
        movie.medium_cover_image ||
        movie.small_cover_image ||
        `${siteUrl()}/favicon.ico`,
      url: canonical,
      mainEntityOfPage: canonical,
    };
    if (movie.year) payload.datePublished = String(movie.year);
    if (movie.imdb_code) payload.sameAs = `https://www.imdb.com/title/${movie.imdb_code}/`;
    if (movie.rating) {
      payload.aggregateRating = {
        "@type": "AggregateRating",
        ratingValue: Number(movie.rating),
        bestRating: 10,
        worstRating: 0,
        ratingCount: Math.max(Number(movie.like_count) || 0, 1),
      };
    }
    if (movie.genres && movie.genres.length) payload.genre = movie.genres;
    return payload;
  }

  function setPage(options) {
    const {
      title,
      description,
      canonical,
      image,
      type = "website",
      robots = "index,follow",
      jsonLd = null,
    } = options;

    document.title = title;
    upsertMeta("name", "description", description);
    upsertMeta("name", "robots", robots);
    upsertLink("canonical", canonical);
    upsertLink("sitemap", `${siteUrl()}/sitemap.xml`);
    if (document.querySelector('link[rel="sitemap"]')) {
      document.querySelector('link[rel="sitemap"]').setAttribute("type", "application/xml");
      document.querySelector('link[rel="sitemap"]').setAttribute("title", "Sitemap");
    }
    upsertMeta("property", "og:type", type);
    upsertMeta("property", "og:site_name", siteName());
    upsertMeta("property", "og:title", title);
    upsertMeta("property", "og:description", description);
    upsertMeta("property", "og:url", canonical);
    upsertMeta("property", "og:image", image);
    upsertMeta("name", "twitter:card", "summary_large_image");
    upsertMeta("name", "twitter:title", title);
    upsertMeta("name", "twitter:description", description);
    upsertMeta("name", "twitter:image", image);
    upsertJsonLd(jsonLd);
  }

  function setHome() {
    setPage({
      title: homeTitle(),
      description: homeDescription(),
      canonical: `${siteUrl()}/`,
      image: `${siteUrl()}/favicon.ico`,
      type: "website",
      jsonLd: homeJsonLd(),
    });
  }

  function setBrowse(query) {
    const title = query
      ? `Search: ${query} - ${siteName()}`
      : `Browse YIFY Movies - ${siteName()}`;
    const description = query
      ? `YIFY movie search results for "${query}". Download HD movies at the smallest file size.`
      : "Browse the full YIFY movie catalog. Download HD movies in 720p, 1080p, 2160p 4K and x265.";
    const canonical = query
      ? `${siteUrl()}/browse?q=${encodeURIComponent(query)}`
      : `${siteUrl()}/browse`;

    setPage({
      title,
      description,
      canonical,
      image: `${siteUrl()}/favicon.ico`,
      type: "website",
      jsonLd: null,
    });
  }

  function setMovie(movie) {
    const slug = movie.slug || `movie-${movie.id}`;
    const canonical = `${siteUrl()}/movies/${slug}`;
    const title = `${movie.title || "Movie"} (${movie.year || ""}) YIFY Download - ${siteName()}`;
    setPage({
      title,
      description: movieDescription(movie),
      canonical,
      image:
        movie.large_cover_image ||
        movie.medium_cover_image ||
        movie.small_cover_image ||
        `${siteUrl()}/favicon.ico`,
      type: "video.movie",
      jsonLd: movieJsonLd(movie, canonical),
    });
  }

  function setAdmin() {
    setPage({
      title: `Admin - ${siteName()}`,
      description: "Admin panel",
      canonical: `${siteUrl()}/twojastara`,
      image: `${siteUrl()}/favicon.ico`,
      type: "website",
      robots: "noindex,nofollow",
      jsonLd: null,
    });
  }

  window.YtsSeo = { setHome, setBrowse, setMovie, setAdmin, setPage, homeTitle, homeDescription };
})();
