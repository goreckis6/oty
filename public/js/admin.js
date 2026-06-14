(function () {
  const TOKEN_KEY = "yts_admin_token";

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function setToken(token) {
    localStorage.setItem(TOKEN_KEY, token);
  }

  function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
  }

  async function api(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch(`/api/v1${path}`, { ...options, headers });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
    return data;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function escapeAttr(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function renderLogin(app, onSuccess) {
    app.innerHTML = `
      <div class="admin-wrap">
        <div class="admin-card">
          <h1>Admin Panel</h1>
          <p class="admin-sub">Log in to manage movies and scraping</p>
          <form id="adminLoginForm" class="admin-form">
            <label>Username<input type="text" id="adminUser" autocomplete="username" required /></label>
            <label>Password<input type="password" id="adminPass" autocomplete="current-password" required /></label>
            <button type="submit" class="btn-browse">Log in</button>
            <p class="admin-error" id="adminError" hidden></p>
          </form>
        </div>
      </div>`;

    document.getElementById("adminLoginForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const errEl = document.getElementById("adminError");
      errEl.hidden = true;
      try {
        const data = await api("/admin/login", {
          method: "POST",
          body: JSON.stringify({
            username: document.getElementById("adminUser").value,
            password: document.getElementById("adminPass").value,
          }),
        });
        setToken(data.token);
        onSuccess();
      } catch (err) {
        errEl.textContent = err.message;
        errEl.hidden = false;
      }
    });
  }

  function renderDashboard(app) {
    let moviesPage = 1;
    let moviesLimit = 100;
    let autoRefreshTimer = null;
    const selectedIds = new Set();

    function updateBulkBar() {
      const bar = document.getElementById("adminBulkBar");
      const count = selectedIds.size;
      if (!bar) return;
      bar.hidden = count === 0;
      document.getElementById("adminBulkCount").textContent = String(count);
      const selectAll = document.getElementById("adminSelectAll");
      if (selectAll) {
        const boxes = [...document.querySelectorAll(".admin-movie-check")];
        selectAll.checked = boxes.length > 0 && boxes.every((b) => b.checked);
        selectAll.indeterminate = count > 0 && !selectAll.checked;
      }
    }

    function getVisibleIds() {
      return [...document.querySelectorAll(".admin-movie-check")].map((b) => parseInt(b.value, 10));
    }

    app.innerHTML = `
      <div class="admin-wrap">
        <div class="admin-panel">
          <div class="admin-panel__head">
            <h1>Movie Database</h1>
            <button type="button" class="btn-admin-outline" id="adminLogout">Logout</button>
          </div>

          <div class="admin-stats" id="adminStats">
            <div class="admin-stat"><span>Movies</span><strong id="statCount">—</strong></div>
            <div class="admin-stat"><span>Last scrape</span><strong id="statLast">—</strong></div>
            <div class="admin-stat"><span>Last batch</span><strong id="statBatch">—</strong></div>
            <div class="admin-stat"><span>NEW</span><strong id="statNew">—</strong></div>
          </div>

          <section class="admin-section">
            <h2>Scrape from YTS</h2>
            <p class="admin-hint">Pobiera kolejne nowe filmy z yts.bz i dopisuje do bazy SQLite (bez usuwania poprzednich).</p>
            <form id="scrapeForm" class="admin-scrape">
              <label>
                Liczba filmów
                <input type="number" id="scrapeCount" min="1" max="50" value="10" />
              </label>
              <button type="submit" class="btn-browse" id="scrapeBtn">Start scraping</button>
            </form>
            <pre class="admin-log" id="adminLog">Ready.</pre>
          </section>

          <section class="admin-section">
            <h2>Auto scraping</h2>
            <p class="admin-hint">Automatyczny scraping w tle. Minimalny interwał: 5 minut.</p>
            <form id="autoScrapeForm" class="admin-scrape admin-scrape--auto">
              <label class="admin-check">
                <input type="checkbox" id="autoScrapeEnabled" />
                Włączone
              </label>
              <label>
                Co ile minut
                <input type="number" id="autoScrapeInterval" min="5" max="1440" value="60" />
              </label>
              <label>
                Filmów na cykl
                <input type="number" id="autoScrapeCount" min="1" max="50" value="10" />
              </label>
              <button type="submit" class="btn-browse" id="autoScrapeSave">Zapisz</button>
            </form>
            <div class="admin-auto-status" id="autoScrapeStatus">Ładowanie statusu…</div>
          </section>

          <section class="admin-section">
            <h2>Filmy w bazie</h2>
            <p class="admin-hint">Każdy scraping dopisuje nowe filmy do bazy (istniejące są pomijane). Ostatnio dodane mają NEW do następnego scrapingu.</p>
            <div class="admin-list-toolbar">
              <label>
                Na stronę
                <select id="adminMoviesLimit">
                  <option value="100">100</option>
                  <option value="200">200</option>
                  <option value="300">300</option>
                  <option value="500">500</option>
                </select>
              </label>
              <span class="admin-list-meta" id="adminMoviesMeta">—</span>
              <div class="admin-pagination" id="adminMoviesPagination"></div>
            </div>
            <div class="admin-bulk-bar" id="adminBulkBar" hidden>
              <span><strong id="adminBulkCount">0</strong> zaznaczonych</span>
              <button type="button" class="btn-admin-delete" id="adminBulkDelete">Usuń zaznaczone</button>
            </div>
            <div class="admin-movies-wrap">
              <table class="admin-movies" id="adminMoviesTable">
                <thead>
                  <tr>
                    <th class="admin-movies__check">
                      <input type="checkbox" id="adminSelectAll" title="Zaznacz wszystkie na stronie" />
                    </th>
                    <th></th>
                    <th>Tytuł</th>
                    <th>Rok</th>
                    <th>Rating</th>
                    <th>Slug</th>
                    <th>Akcje</th>
                  </tr>
                </thead>
                <tbody id="adminMoviesBody">
                  <tr><td colspan="7" class="admin-movies-empty">Ładowanie…</td></tr>
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </div>`;

    document.getElementById("adminLogout").addEventListener("click", () => {
      if (autoRefreshTimer) clearInterval(autoRefreshTimer);
      clearToken();
      window.YtsAdmin.render(app);
    });

    document.getElementById("adminMoviesLimit").value = String(moviesLimit);
    document.getElementById("adminMoviesLimit").addEventListener("change", (e) => {
      moviesLimit = parseInt(e.target.value, 10) || 100;
      moviesPage = 1;
      loadMovies();
    });

    function renderMoviesPagination(data) {
      const el = document.getElementById("adminMoviesPagination");
      const totalPages = data.total_pages || 1;
      if (totalPages <= 1) {
        el.innerHTML = "";
        return;
      }
      el.innerHTML = `
        <button type="button" class="btn-admin-outline" data-page="prev" ${moviesPage <= 1 ? "disabled" : ""}>←</button>
        <span>${moviesPage} / ${totalPages}</span>
        <button type="button" class="btn-admin-outline" data-page="next" ${moviesPage >= totalPages ? "disabled" : ""}>→</button>`;
      el.querySelectorAll("button[data-page]").forEach((btn) => {
        btn.addEventListener("click", () => {
          if (btn.dataset.page === "prev" && moviesPage > 1) moviesPage -= 1;
          if (btn.dataset.page === "next" && moviesPage < totalPages) moviesPage += 1;
          loadMovies();
        });
      });
    }

    function formatAdminTime(iso) {
      if (!iso) return "";
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return iso;
      return d.toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "medium" });
    }

    function formatAutoStatus(s) {
      const lines = [];
      lines.push(s.enabled ? "Status: włączone" : "Status: wyłączone");
      if (s.enabled && s.scheduler_alive === false) {
        lines.push("Scheduler: nie działa (zrestartuj API)");
      }
      if (s.running) lines.push("Teraz: scraping w toku…");
      if (s.next_run) {
        const label = s.next_run_overdue ? "Następny (opóźniony)" : "Następny";
        lines.push(`${label}: ${formatAdminTime(s.next_run)}`);
      }
      if (s.last_run) lines.push(`Ostatni auto: ${formatAdminTime(s.last_run)}`);
      if (s.last_result) {
        const r = s.last_result;
        if (r.error) lines.push(`Błąd: ${r.error}`);
        else lines.push(`Ostatni wynik: +${r.saved || 0} (w bazie: ${r.total_in_db || "?"})`);
      }
      return lines.join(" · ");
    }

    async function loadAutoScrape() {
      const statusEl = document.getElementById("autoScrapeStatus");
      try {
        const s = await api("/admin/auto-scrape");
        document.getElementById("autoScrapeEnabled").checked = !!s.enabled;
        document.getElementById("autoScrapeInterval").value = s.interval_minutes || 60;
        document.getElementById("autoScrapeCount").value = s.count || 10;
        statusEl.textContent = formatAutoStatus(s);
      } catch (err) {
        statusEl.textContent = `Błąd: ${err.message}`;
      }
    }

    document.getElementById("autoScrapeForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = document.getElementById("autoScrapeSave");
      btn.disabled = true;
      try {
        await api("/admin/auto-scrape", {
          method: "POST",
          body: JSON.stringify({
            enabled: document.getElementById("autoScrapeEnabled").checked,
            interval_minutes: parseInt(document.getElementById("autoScrapeInterval").value, 10) || 60,
            count: parseInt(document.getElementById("autoScrapeCount").value, 10) || 10,
          }),
        });
        await loadAutoScrape();
        loadStats();
      } catch (err) {
        document.getElementById("autoScrapeStatus").textContent = `Błąd: ${err.message}`;
      } finally {
        btn.disabled = false;
      }
    });

    async function loadStats() {
      try {
        const s = await api("/admin/stats");
        document.getElementById("statCount").textContent = s.movies_count;
        document.getElementById("statLast").textContent = s.last_scrape || "never";
        document.getElementById("statBatch").textContent = s.last_scrape_count || "—";
        document.getElementById("statNew").textContent = s.new_count ?? "—";
      } catch {
        clearToken();
        window.YtsAdmin.render(app);
      }
    }

    async function loadMovies() {
      const tbody = document.getElementById("adminMoviesBody");
      try {
        const data = await api(`/admin/movies?page=${moviesPage}&limit=${moviesLimit}`);
        const movies = data.movies || [];
        document.getElementById("adminMoviesMeta").textContent =
          `Strona ${data.page}/${data.total_pages} · ${data.movie_count} filmów`;
        renderMoviesPagination(data);
        if (!movies.length) {
          tbody.innerHTML = `<tr><td colspan="7" class="admin-movies-empty">Brak filmów w bazie.</td></tr>`;
          updateBulkBar();
          return;
        }
        tbody.innerHTML = movies
          .map(
            (m) => `
          <tr class="${m.is_new ? "admin-movies__row--new" : ""}${m.is_duplicate_title ? " admin-movies__row--dup" : ""}">
            <td class="admin-movies__check">
              <input type="checkbox" class="admin-movie-check" value="${m.id}" ${selectedIds.has(m.id) ? "checked" : ""} />
            </td>
            <td>
              ${m.is_new ? '<span class="badge-new">NEW</span>' : ""}
              ${m.is_duplicate_title ? '<span class="badge-dup" title="Powtarzający się tytuł">DUP</span>' : ""}
            </td>
            <td class="admin-movies__title">${escapeHtml(m.title || "—")}${m.is_duplicate_title ? ' <span class="admin-movies__dup-hint">(duplikat tytułu)</span>' : ""}</td>
            <td>${m.year || "—"}</td>
            <td>${m.rating != null ? Number(m.rating).toFixed(1) : "—"}</td>
            <td class="admin-movies__slug">${escapeHtml(m.slug || "—")}</td>
            <td class="admin-movies__actions">
              <a class="admin-movies__link" href="${escapeHtml(m.url)}" target="_blank" rel="noopener">Podgląd</a>
              <button type="button" class="btn-admin-delete" data-id="${m.id}" data-title="${escapeAttr(m.title || "")}">Usuń</button>
            </td>
          </tr>`
          )
          .join("");
        updateBulkBar();
      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="7" class="admin-movies-empty">Błąd: ${escapeHtml(err.message)}</td></tr>`;
      }
    }

    document.getElementById("adminSelectAll").addEventListener("change", (e) => {
      const checked = e.target.checked;
      getVisibleIds().forEach((id) => {
        if (checked) selectedIds.add(id);
        else selectedIds.delete(id);
      });
      document.querySelectorAll(".admin-movie-check").forEach((box) => {
        box.checked = checked;
      });
      updateBulkBar();
    });

    document.getElementById("adminMoviesBody").addEventListener("change", (e) => {
      const box = e.target.closest(".admin-movie-check");
      if (!box) return;
      const id = parseInt(box.value, 10);
      if (box.checked) selectedIds.add(id);
      else selectedIds.delete(id);
      updateBulkBar();
    });

    document.getElementById("adminBulkDelete").addEventListener("click", async () => {
      const ids = [...selectedIds];
      if (!ids.length) return;
      if (!confirm(`Usunąć ${ids.length} zaznaczonych filmów z bazy?`)) return;
      const btn = document.getElementById("adminBulkDelete");
      btn.disabled = true;
      try {
        const result = await api("/admin/movies/bulk-delete", {
          method: "POST",
          body: JSON.stringify({ ids }),
        });
        ids.forEach((id) => selectedIds.delete(id));
        loadStats();
        loadMovies();
        alert(`Usunięto ${result.deleted} filmów.`);
      } catch (err) {
        alert(err.message);
      } finally {
        btn.disabled = false;
      }
    });

    document.getElementById("adminMoviesBody").addEventListener("click", async (e) => {
      const btn = e.target.closest(".btn-admin-delete");
      if (!btn) return;
      const id = btn.dataset.id;
      const title = btn.dataset.title || id;
      if (!confirm(`Usunąć film „${title}” z bazy?`)) return;
      btn.disabled = true;
      try {
        await api(`/admin/movies/${id}`, { method: "DELETE" });
        selectedIds.delete(parseInt(id, 10));
        loadStats();
        loadMovies();
      } catch (err) {
        alert(err.message);
        btn.disabled = false;
      }
    });

    document.getElementById("scrapeForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = document.getElementById("scrapeBtn");
      const log = document.getElementById("adminLog");
      const count = parseInt(document.getElementById("scrapeCount").value, 10) || 10;
      btn.disabled = true;
      log.textContent = `Scraping ${count} movies…\n`;
      try {
        const result = await api("/admin/scrape", {
          method: "POST",
          body: JSON.stringify({ count }),
        });
        log.textContent += (result.logs || []).join("\n") + "\n";
        log.textContent += `\n✓ Dodano ${result.saved} nowych filmów (w bazie: ${result.total_in_db})`;
        if (result.skipped) {
          log.textContent += `, pominięto ${result.skipped} już istniejących`;
        }
        if (result.skipped_duplicates) {
          log.textContent += `, ${result.skipped_duplicates} duplikatów tytułu`;
        }
        if (result.seo_urls && result.seo_urls.length) {
          log.textContent += `\nSEO: ${result.seo_urls.length} stron dodanych do sitemap.`;
        }
        loadStats();
        loadMovies();
      } catch (err) {
        log.textContent += `\nError: ${err.message}`;
      } finally {
        btn.disabled = false;
      }
    });

    loadStats();
    loadMovies();
    loadAutoScrape();
    autoRefreshTimer = setInterval(() => {
      loadAutoScrape();
      loadStats();
    }, 30000);
  }

  async function render(app) {
    const token = getToken();
    if (!token) {
      renderLogin(app, () => render(app));
      return;
    }
    try {
      await api("/admin/me");
      renderDashboard(app);
    } catch {
      clearToken();
      renderLogin(app, () => render(app));
    }
  }

  window.YtsAdmin = { render };
})();
