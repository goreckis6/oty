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

  function initSiteMeta() {
    const tagline = document.getElementById("siteTagline");
    const footer = document.getElementById("footerText");
    const name = cfg().siteName || "YTS";
    document.title = `${name} — Movies`;
    if (tagline) tagline.textContent = cfg().siteTagline || "HD at smallest size";
    if (footer) footer.textContent = `© ${new Date().getFullYear()} ${name} — The Official Home of YIFY Movies`;
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

  function showError(msg) {
    const api = cfg().apiBase || "/api/v1";
    app.innerHTML = `
      <div class="error-box">
        <p><strong>Could not reach API</strong></p>
        <p>${escapeHtml(msg)}</p>
        <code>API: ${escapeHtml(api)}</code>
      </div>`;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
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
      <a class="movie-box" href="/movie/${m.id}">
        <div class="movie-box__img">
          <img src="${escapeHtml(img)}" alt="${escapeHtml(m.title)}" loading="lazy" />
          <div class="movie-box__rating">${rating} <span>/ 10</span></div>
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
    } catch (err) {
      showError(err.message);
    }
  }

  async function renderMovie(id) {
    setFiltersVisible(false);
    showLoading();

    try {
      const [details, suggestions] = await Promise.all([
        YtsApi.movieDetails(id),
        YtsApi.movieSuggestions(id).catch(() => ({ movies: [] })),
      ]);

      const m = details.movie;
      const torrents = (m.torrents || [])
        .map((t) => {
          const magnet = YtsApi.buildMagnet(t, m.title_long || m.title);
          const torrentUrl = t.url || "#";
          return `
            <tr>
              <td><strong>${escapeHtml(t.quality)}</strong> ${t.type ? `<span style="color:var(--text-muted)">${escapeHtml(t.type)}</span>` : ""}</td>
              <td>${escapeHtml(t.size || "—")}</td>
              <td class="seeds">${t.seeds ?? 0}</td>
              <td class="peers">${t.peers ?? 0}</td>
              <td>
                <a class="btn-dl" href="${escapeHtml(torrentUrl)}" target="_blank" rel="noopener">Torrent</a>
                <a class="btn-dl btn-magnet" href="${escapeHtml(magnet)}">Magnet</a>
              </td>
            </tr>`;
        })
        .join("");

      const genres = (m.genres || [])
        .map((g) => `<a class="genre-tag" href="/browse?genre=${encodeURIComponent(g)}">${escapeHtml(g)}</a>`)
        .join("");

      const trailerBtn = m.yt_trailer_code
        ? `<a class="btn-trailer" href="https://www.youtube.com/watch?v=${escapeHtml(m.yt_trailer_code)}" target="_blank" rel="noopener">▶ Watch Trailer</a>`
        : "";

      app.innerHTML = `
        <article class="movie-detail">
          <div class="movie-detail__hero">
            <div class="movie-detail__bg" style="background-image:url('${escapeHtml(m.background_image || m.large_cover_image || "")}')"></div>
            <div class="movie-detail__hero-inner">
              <img class="movie-detail__poster" src="${escapeHtml(m.medium_cover_image || m.large_cover_image || "")}" alt="${escapeHtml(m.title)}" />
              <div class="movie-detail__info">
                <h1 class="movie-detail__title">${escapeHtml(m.title)}</h1>
                <p class="movie-detail__year">${m.year || ""} · ${m.runtime || "?"} min · ${escapeHtml(m.language || "")} · ${escapeHtml(m.mpa_rating || "")}</p>
                <div class="movie-detail__stats">
                  <span class="rating">★ ${m.rating ? m.rating.toFixed(1) : "—"}</span>
                  <span>${(m.download_count || 0).toLocaleString()} downloads</span>
                  <span>${(m.like_count || 0).toLocaleString()} likes</span>
                </div>
                <div class="movie-detail__genres">${genres}</div>
                <p class="movie-detail__desc">${escapeHtml(m.description_full || m.description_intro || m.summary || "")}</p>
                <div class="movie-detail__trailer">${trailerBtn}</div>
              </div>
            </div>
          </div>

          <div class="torrents">
            <div class="torrents__title">Available Torrents</div>
            <table>
              <thead>
                <tr><th>Quality</th><th>Size</th><th>Seeds</th><th>Peers</th><th>Download</th></tr>
              </thead>
              <tbody>${torrents || "<tr><td colspan='5'>No torrents listed.</td></tr>"}</tbody>
            </table>
          </div>

          ${suggestions.movies && suggestions.movies.length ? `
          <section class="section-block">
            <div class="section-head"><h2>Similar YIFY Movies</h2></div>
            ${renderGrid(suggestions.movies)}
          </section>` : ""}
        </article>`;

      document.title = `${m.title} (${m.year}) — ${cfg().siteName || "YTS"}`;
    } catch (err) {
      showError(err.message);
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
    const movieMatch = path.match(/^\/movie\/(\d+)$/);
    if (movieMatch) return { view: "movie", id: movieMatch[1] };
    return { view: "home" };
  }

  function migrateHashUrl() {
    if (!location.hash.startsWith("#/")) return;
    const target = location.hash.slice(1) || "/";
    history.replaceState(null, "", target);
  }

  async function router() {
    initSiteMeta();
    const route = parseRoute();

    if (route.view === "home") return renderHome();
    if (route.view === "browse") return renderBrowse(route.page);
    if (route.view === "movie") return renderMovie(route.id);
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
    if (!url || url.startsWith("/api/")) return;
    e.preventDefault();
    navigate(url);
  });

  window.addEventListener("popstate", router);

  migrateHashUrl();
  initSiteMeta();
  router();
})();
