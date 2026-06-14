(function () {
  const app = document.getElementById("app");
  const filtersBar = document.getElementById("filtersBar");
  const searchForm = document.getElementById("searchForm");
  const searchInput = document.getElementById("searchInput");
  const filterQuality = document.getElementById("filterQuality");
  const filterGenre = document.getElementById("filterGenre");
  const filterRating = document.getElementById("filterRating");
  const filterSort = document.getElementById("filterSort");
  const applyFilters = document.getElementById("applyFilters");

  const cfg = () => window.YTS_CONFIG || {};

  let state = {
    page: 1,
    query: "",
    quality: "All",
    genre: "All",
    rating: "0",
    sort: "date_added",
  };

  let brandingCache = null;

  async function fetchBranding() {
    if (brandingCache) return brandingCache;
    try {
      const base = cfg().apiBase || "/api/v1";
      const res = await fetch(`${base}/site/branding`);
      const data = await res.json();
      brandingCache = data;
      window.YTS_CONFIG = {
        ...cfg(),
        siteName: data.siteName,
        siteTagline: data.siteTagline,
        logoUrl: data.logoUrl,
        logoType: data.logoType,
      };
    } catch {
      brandingCache = {
        siteName: cfg().siteName || "YTS",
        siteTagline: cfg().siteTagline || "HD movies at the smallest file size",
        logoUrl: "",
        logoType: "text",
      };
    }
    return brandingCache;
  }

  function applyBranding(b) {
    const tagline = document.getElementById("siteTagline");
    const footer = document.getElementById("footerText");
    const logoText = document.getElementById("siteLogoText");
    const logoImg = document.getElementById("siteLogoImg");
    const name = b.siteName || cfg().siteName || "YTS";
    const tag = b.siteTagline || cfg().siteTagline || "HD movies at the smallest file size";

    if (tagline) tagline.textContent = tag;
    if (footer) footer.textContent = `© ${new Date().getFullYear()} ${name} — The Official Home of YIFY Movies`;

    if (b.logoType === "image" && b.logoUrl && logoImg) {
      logoImg.src = b.logoUrl;
      logoImg.alt = name;
      logoImg.hidden = false;
      if (logoText) logoText.hidden = true;
    } else {
      if (logoText) {
        logoText.textContent = name;
        logoText.hidden = false;
      }
      if (logoImg) logoImg.hidden = true;
    }
  }

  async function initSiteMeta() {
    applyBranding(await fetchBranding());
  }

  function navigate(url) {
    if (url === location.pathname + location.search) {
      router();
      return;
    }
    history.pushState(null, "", url);
    router();
  }

  function browseUrl() {
    const params = new URLSearchParams();
    if (state.query) params.set("q", state.query);
    if (state.genre !== "All") params.set("genre", state.genre);
    if (state.page > 1) params.set("page", String(state.page));
    const qs = params.toString();
    return qs ? `/browse?${qs}` : "/browse";
  }

  function showLoading() {
    app.innerHTML = `<div class="loading"><div class="spinner"></div><p>Loading…</p></div>`;
  }

  function showError(msg, title = "Could not reach API") {
    const api = cfg().apiBase || "/api/v1";
    app.innerHTML = `
      <div class="error-box">
        <p><strong>${escapeHtml(title)}</strong></p>
        <p>${escapeHtml(msg)}</p>
        <code>API: ${escapeHtml(api)}</code>
      </div>`;
  }

  function showNotFound(label) {
    app.innerHTML = `
      <div class="error-box">
        <p><strong>Movie not found</strong></p>
        <p>${escapeHtml(label || "This movie is not in the catalog.")}</p>
        <p><a href="/">← Back to home</a></p>
      </div>`;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function movieHref(m) {
    if (m.slug) return `/movies/${m.slug}`;
    const t = (m.title || "movie").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    return `/movies/${t}-${m.year || ""}`;
  }

  function setFiltersVisible(show) {
    filtersBar.classList.toggle("is-hidden", !show);
  }

  function movieCard(m, featured = false) {
    const img = m.medium_cover_image || m.small_cover_image || m.large_cover_image || "";
    const genres = (m.genres || []).slice(0, 2);
    const rating = m.rating ? m.rating.toFixed(1) : "0.0";
    const genreHtml = genres
      .map((g) => `<span class="movie-box__genre">${escapeHtml(g)}</span>`)
      .join("");

    return `
      <a class="movie-box" href="${movieHref(m)}">
        <div class="movie-box__img">
          <img src="${escapeHtml(img)}" alt="${escapeHtml(m.title)}" loading="lazy" />
          <div class="movie-box__rating">${rating} <span>/ 10</span></div>
          ${m.is_new ? '<div class="badge-new badge-new--card">NEW</div>' : ""}
          ${m.year ? `<div class="movie-box__year">${m.year}</div>` : ""}
        </div>
        <div class="movie-box__title">${escapeHtml(m.title)}</div>
        ${genreHtml ? `<div class="movie-box__genres">${genreHtml}</div>` : ""}
      </a>`;
  }

  function renderGrid(movies, featured = false) {
    if (!movies || !movies.length) {
      return `<p class="empty-msg">No movies found.</p>`;
    }
    const rowClass = featured ? "movies-row movies-row--featured" : "movies-row";
    return `<div class="${rowClass}">${movies.map((m) => movieCard(m, featured)).join("")}</div>`;
  }

  function renderPagination(movieCount, limit, page) {
    const totalPages = Math.max(1, Math.ceil(movieCount / limit));
    if (totalPages <= 1) return "";

    const pages = [];
    const start = Math.max(1, page - 2);
    const end = Math.min(totalPages, page + 2);

    if (page > 1) pages.push(`<button data-page="${page - 1}">← Prev</button>`);
    for (let i = start; i <= end; i++) {
      pages.push(`<button data-page="${i}" class="${i === page ? "active" : ""}">${i}</button>`);
    }
    if (page < totalPages) pages.push(`<button data-page="${page + 1}">Next →</button>`);

    return `
      <div class="pagination" id="pagination">
        <span class="pagination__info">Page ${page} of ${totalPages} (${movieCount} movies)</span>
        ${pages.join("")}
      </div>`;
  }

  function bindPagination(movieCount, limit, page) {
    const el = document.getElementById("pagination");
    if (!el) return;
    el.querySelectorAll("button[data-page]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.page = parseInt(btn.dataset.page, 10);
        navigate(browseUrl());
      });
    });
  }

  async function loadMovies(opts = {}) {
    const page = opts.page || state.page;
    const params = {
      page,
      limit: 20,
      query_term: opts.query ?? state.query,
      quality: opts.quality ?? state.quality,
      genre: opts.genre ?? state.genre,
      minimum_rating: opts.rating ?? state.rating,
      sort_by: opts.sort ?? state.sort,
      order_by: "desc",
    };

    const data = await YtsApi.listMovies(params);
    return { ...data, page };
  }

  async function renderHome() {
    setFiltersVisible(true);
    showLoading();

    try {
      const [all, upcoming] = await Promise.all([
        YtsApi.listMovies({ limit: 20, sort_by: "date_added", order_by: "desc" }),
        YtsApi.listUpcoming().catch(() => ({ movies: [] })),
      ]);

      const movies = all.movies || [];
      const popular = [...movies].sort((a, b) => (b.rating || 0) - (a.rating || 0)).slice(0, 4);
      const latest = movies.slice(0, 8);
      const name = cfg().siteName || "YTS";

      app.innerHTML = `
        <div class="home-hero">
          <div class="container">
            <h1>Download YTS YIFY movies: HD smallest size</h1>
            <p>
              Welcome to <strong>${escapeHtml(name)}</strong>.
              Browse and download YIFY movies in excellent 720p, 1080p, 2160p 4K and 3D quality,
              all at the smallest file size.
            </p>
          </div>
        </div>

        <section class="section-block">
          <div class="section-head">
            <h2>Popular YTS Downloads</h2>
            <a href="/browse?sort=rating">More featured →</a>
          </div>
          ${renderGrid(popular, true)}
        </section>

        <section class="section-block">
          <div class="section-head">
            <h2>Latest YTS YIFY Movies Torrents</h2>
            <a href="/browse">Browse All →</a>
          </div>
          ${renderGrid(latest)}
        </section>

        ${upcoming.movies && upcoming.movies.length ? `
        <section class="section-block">
          <div class="section-head">
            <h2>Upcoming YTS YIFY Movies</h2>
          </div>
          <div class="movies-row movies-row--upcoming">${upcoming.movies.map((m) => movieCard(m)).join("")}</div>
        </section>` : ""}`;
      if (window.YtsSeo) window.YtsSeo.setHome();
    } catch (err) {
      showError(err.message);
    }
  }

  async function renderBrowse(page = 1) {
    setFiltersVisible(true);
    syncFiltersToUI();
    showLoading();

    try {
      state.page = page;
      const data = await loadMovies({ page });
      const title = state.query
        ? `Search: "${state.query}"`
        : state.genre !== "All"
          ? `Genre: ${state.genre}`
          : "Browse Movies";

      app.innerHTML = `
        <h1 class="page-title">${escapeHtml(title)}</h1>
        <section class="section-block" style="margin-top:0">
          ${renderGrid(data.movies)}
          ${renderPagination(data.movie_count, data.limit, data.page_number)}
        </section>`;

      bindPagination(data.movie_count, data.limit, data.page_number);
      window.scrollTo({ top: 0, behavior: "smooth" });
      if (window.YtsSeo) window.YtsSeo.setBrowse(state.query);
    } catch (err) {
      showError(err.message);
    }
  }

  async function renderMovie(slugOrId) {
    setFiltersVisible(false);
    showLoading();

    try {
      const [details, suggestions] = await Promise.all([
        YtsApi.movieDetails(slugOrId),
        YtsApi.movieSuggestions(slugOrId).catch(() => ({ movies: [] })),
      ]);

      const m = details.movie;

      if (m.slug && location.pathname !== `/movies/${m.slug}`) {
        history.replaceState(null, "", `/movies/${m.slug}`);
      }

      const torrentCards = (m.torrents || [])
        .map((t) => {
          const magnet = YtsApi.buildMagnet(t, m.title_long || m.title);
          const torrentUrl = t.url || "#";
          return `
            <div class="dl-box">
              <div class="dl-box__quality">${escapeHtml(t.quality)}</div>
              <div class="dl-box__size">${escapeHtml(t.size || "—")}</div>
              <div class="dl-box__peers">
                <span class="seeds">${t.seeds ?? 0} seeds</span>
                <span class="peers">${t.peers ?? 0} peers</span>
              </div>
              <div class="dl-box__actions">
                <a class="btn-dl" href="${escapeHtml(torrentUrl)}" target="_blank" rel="noopener">Download</a>
                <a class="btn-dl btn-magnet" href="${escapeHtml(magnet)}">Magnet</a>
              </div>
            </div>`;
        })
        .join("");

      const genres = (m.genres || [])
        .map((g) => `<a class="genre-tag" href="/browse?genre=${encodeURIComponent(g)}">${escapeHtml(g)}</a>`)
        .join("");

      const cast = (m.cast || []).slice(0, 8)
        .map((c) => `<span class="cast-name">${escapeHtml(c.name || "")}</span>`)
        .join("");

      const screenshots = (m.screenshots || []).filter(Boolean);
      const screenshotHtml = screenshots.length
        ? `
                <section class="movie-section">
                  <h2 class="movie-section__title">Screenshots</h2>
                  <div class="movie-screenshots">
                    ${screenshots
                      .map(
                        (src, i) => `
                      <a class="movie-screenshot" href="${escapeHtml(src)}" target="_blank" rel="noopener">
                        <img src="${escapeHtml(src)}" alt="${escapeHtml(m.title)} screenshot ${i + 1}" loading="lazy" />
                      </a>`
                      )
                      .join("")}
                  </div>
                </section>`
        : "";

      const trailerCode = m.yt_trailer_code || "";
      const trailerEmbed = m.trailer_embed || (trailerCode ? `https://www.youtube.com/embed/${trailerCode}` : "");
      const trailerSection = trailerEmbed
        ? `
                <section class="movie-section">
                  <h2 class="movie-section__title">Trailer</h2>
                  <div class="movie-trailer">
                    <iframe
                      src="${escapeHtml(trailerEmbed)}"
                      title="${escapeHtml(m.title)} trailer"
                      loading="lazy"
                      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                      allowfullscreen
                    ></iframe>
                  </div>
                </section>`
        : "";

      const subtitles = m.subtitles || [];
      const subtitleHtml = subtitles.length
        ? `
                <section class="movie-section">
                  <h2 class="movie-section__title">Subtitles</h2>
                  <div class="subtitle-list">
                    ${subtitles
                      .map(
                        (s) =>
                          `<span class="subtitle-badge" title="${escapeHtml(s.label || s.code)}">${escapeHtml((s.code || "").toUpperCase())}</span>`
                      )
                      .join("")}
                  </div>
                  <p class="subtitle-note">Included subtitle languages in YIFY torrent.</p>
                </section>`
        : "";

      const trailerBtn = trailerCode
        ? `<a class="btn-trailer" href="https://www.youtube.com/watch?v=${escapeHtml(trailerCode)}" target="_blank" rel="noopener">▶ Trailer</a>`
        : "";

      const rating = m.rating ? m.rating.toFixed(1) : "—";

      app.innerHTML = `
        <article class="movie-page">
          <div class="movie-banner" style="background-image:url('${escapeHtml(m.background_image || m.large_cover_image || "")}')">
            <div class="movie-banner__overlay"></div>
          </div>

          <div class="movie-page__inner container">
            <div class="movie-layout">
              <aside class="movie-sidebar">
                <img class="movie-sidebar__poster" src="${escapeHtml(m.large_cover_image || m.medium_cover_image || "")}" alt="${escapeHtml(m.title)}" />
                <div class="imdb-box">
                  <span class="imdb-box__score">${rating}</span>
                  <span class="imdb-box__label">/ 10</span>
                </div>
                <ul class="movie-specs">
                  <li><span>Year</span><strong>${m.year || "—"}</strong></li>
                  <li><span>Runtime</span><strong>${m.runtime || "?"} min</strong></li>
                  <li><span>Language</span><strong>${escapeHtml(m.language || "—")}</strong></li>
                  ${m.imdb_code ? `<li><span>IMDb</span><strong>${escapeHtml(m.imdb_code)}</strong></li>` : ""}
                  <li><span>Downloads</span><strong>${(m.download_count || 0).toLocaleString()}</strong></li>
                  <li><span>Likes</span><strong>${(m.like_count || 0).toLocaleString()}</strong></li>
                </ul>
                ${trailerBtn}
              </aside>

              <div class="movie-main">
                <h1 class="movie-main__title">${escapeHtml(m.title)} <span class="movie-main__year">${m.year || ""}</span></h1>
                <div class="movie-main__genres">${genres}</div>

                <section class="movie-section">
                  <h2 class="movie-section__title">Available in:</h2>
                  <div class="dl-boxes">
                    ${torrentCards || '<p class="empty-msg">No torrents available.</p>'}
                  </div>
                </section>

                <section class="movie-section">
                  <h2 class="movie-section__title">Synopis</h2>
                  <p class="movie-synopsis">${escapeHtml(m.plot_summary || m.synopsis || m.description_full || m.description_intro || m.summary || "No description.")}</p>
                </section>

                ${trailerSection}
                ${screenshotHtml}
                ${subtitleHtml}

                ${cast ? `
                <section class="movie-section">
                  <h2 class="movie-section__title">Cast</h2>
                  <div class="cast-list">${cast}</div>
                </section>` : ""}
              </div>
            </div>

            ${suggestions.movies && suggestions.movies.length ? `
            <section class="section-block movie-similar">
              <div class="section-head"><h2>Similar YIFY Movies</h2></div>
              ${renderGrid(suggestions.movies)}
            </section>` : ""}
          </div>
        </article>`;

      if (window.YtsSeo) window.YtsSeo.setMovie(m);
    } catch (err) {
      if (err.status === 404 || /not found/i.test(err.message || "")) {
        showNotFound(err.message);
      } else {
        showError(err.message);
      }
    }
  }

  function syncFiltersToUI() {
    filterQuality.value = state.quality;
    filterGenre.value = state.genre;
    filterRating.value = state.rating;
    filterSort.value = state.sort;
    searchInput.value = state.query;
  }

  function readFiltersFromUI() {
    state.quality = filterQuality.value;
    state.genre = filterGenre.value;
    state.rating = filterRating.value;
    state.sort = filterSort.value;
    state.query = searchInput.value.trim();
    state.page = 1;
  }

  function parseRoute() {
    const path = location.pathname.replace(/\/+$/, "") || "/";
    const params = new URLSearchParams(location.search);

    if (params.get("genre")) state.genre = params.get("genre");
    if (params.get("q")) state.query = params.get("q");
    if (params.get("sort")) state.sort = params.get("sort");

    if (path === "/" || path === "") return { view: "home" };
    if (path === "/browse") {
      return { view: "browse", page: parseInt(params.get("page") || "1", 10) };
    }
    if (path === "/twojastara") return { view: "admin" };
    const moviesMatch = path.match(/^\/movies\/([^/]+)$/);
    if (moviesMatch) return { view: "movie", slug: decodeURIComponent(moviesMatch[1]) };
    const legacyMatch = path.match(/^\/movie\/(\d+)$/);
    if (legacyMatch) return { view: "movie", slug: legacyMatch[1] };
    return { view: "home" };
  }

  function migrateLegacyUrl() {
    if (location.hash.startsWith("#/")) {
      const target = location.hash.slice(1) || "/";
      history.replaceState(null, "", target);
    }
  }

  async function router() {
    await initSiteMeta();
    const route = parseRoute();

    if (route.view === "home") return renderHome();
    if (route.view === "browse") return renderBrowse(route.page);
    if (route.view === "movie") return renderMovie(route.slug);
    if (route.view === "admin" && window.YtsAdmin) {
      setFiltersVisible(false);
      if (window.YtsSeo) window.YtsSeo.setAdmin();
      return window.YtsAdmin.render(app);
    }
    return renderHome();
  }

  searchForm.addEventListener("submit", (e) => {
    e.preventDefault();
    state.query = searchInput.value.trim();
    state.page = 1;
    navigate(state.query ? `/browse?q=${encodeURIComponent(state.query)}` : "/browse");
  });

  applyFilters.addEventListener("click", () => {
    readFiltersFromUI();
    navigate(browseUrl());
  });

  document.addEventListener("click", (e) => {
    const link = e.target.closest("a[href^='/']");
    if (!link || link.target === "_blank" || e.metaKey || e.ctrlKey || e.shiftKey) return;
    const url = link.getAttribute("href");
    if (!url || url.startsWith("/api/") || url === "/twojastara") return;
    e.preventDefault();
    navigate(url);
  });

  window.addEventListener("popstate", router);

  migrateLegacyUrl();
  router();
})();
