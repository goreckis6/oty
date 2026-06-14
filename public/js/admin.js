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
            <h2>Filmy w bazie</h2>
            <p class="admin-hint">Filmy z ostatniego scrapingu mają oznaczenie NEW do następnego scrapingu.</p>
            <div class="admin-movies-wrap">
              <table class="admin-movies" id="adminMoviesTable">
                <thead>
                  <tr>
                    <th></th>
                    <th>Tytuł</th>
                    <th>Rok</th>
                    <th>Rating</th>
                    <th>Slug</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody id="adminMoviesBody">
                  <tr><td colspan="6" class="admin-movies-empty">Ładowanie…</td></tr>
                </tbody>
              </table>
            </div>
          </section>

          <section class="admin-section">
            <h2>Scrape from YTS</h2>
            <p class="admin-hint">Pobiera filmy z yts.bz i zapisuje do bazy SQLite.</p>
            <form id="scrapeForm" class="admin-scrape">
              <label>
                Liczba filmów
                <input type="number" id="scrapeCount" min="1" max="50" value="10" />
              </label>
              <button type="submit" class="btn-browse" id="scrapeBtn">Start scraping</button>
            </form>
            <pre class="admin-log" id="adminLog">Ready.</pre>
          </section>
        </div>
      </div>`;

    document.getElementById("adminLogout").addEventListener("click", () => {
      clearToken();
      window.YtsAdmin.render(app);
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
        const data = await api("/admin/movies");
        const movies = data.movies || [];
        if (!movies.length) {
          tbody.innerHTML = `<tr><td colspan="6" class="admin-movies-empty">Brak filmów w bazie.</td></tr>`;
          return;
        }
        tbody.innerHTML = movies
          .map(
            (m) => `
          <tr class="${m.is_new ? "admin-movies__row--new" : ""}">
            <td>${m.is_new ? '<span class="badge-new">NEW</span>' : ""}</td>
            <td class="admin-movies__title">${escapeHtml(m.title || "—")}</td>
            <td>${m.year || "—"}</td>
            <td>${m.rating != null ? Number(m.rating).toFixed(1) : "—"}</td>
            <td class="admin-movies__slug">${escapeHtml(m.slug || "—")}</td>
            <td><a class="admin-movies__link" href="${escapeHtml(m.url)}" target="_blank" rel="noopener">Podgląd</a></td>
          </tr>`
          )
          .join("");
      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="6" class="admin-movies-empty">Błąd: ${escapeHtml(err.message)}</td></tr>`;
      }
    }

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
        log.textContent += `\n✓ Zapisano ${result.saved} filmów (w bazie: ${result.total_in_db})`;
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
