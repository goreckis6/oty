(function () {
  const TOKEN_KEY = "yts_admin_token";
  let adminRefreshTimer = null;
  let scrapePollTimer = null;
  let analyticsPollTimer = null;
  let scrapePollInFlight = false;

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function setToken(token) {
    if (token) localStorage.setItem(TOKEN_KEY, token);
  }

  function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
  }

  function isAuthError(err) {
    return err && (err.status === 401 || err.status === 403);
  }

  function clearAdminRefreshTimer() {
    if (adminRefreshTimer) {
      clearInterval(adminRefreshTimer);
      adminRefreshTimer = null;
    }
  }

  function clearScrapePollTimer() {
    if (scrapePollTimer) {
      clearTimeout(scrapePollTimer);
      scrapePollTimer = null;
    }
  }

  function clearAnalyticsPollTimer() {
    if (analyticsPollTimer) {
      clearInterval(analyticsPollTimer);
      analyticsPollTimer = null;
    }
  }

  function clearAllAdminTimers() {
    clearAdminRefreshTimer();
    clearScrapePollTimer();
    clearAnalyticsPollTimer();
  }

  async function api(path, options = {}) {
    const { auth = true, ...fetchOptions } = options;
    const headers = { ...(fetchOptions.headers || {}) };
    const isForm = fetchOptions.body instanceof FormData;
    if (!isForm) headers["Content-Type"] = "application/json";
    const token = getToken();
    if (auth && token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch(`/api/v1${path}`, {
      ...fetchOptions,
      headers,
      credentials: "same-origin",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail;
      const msg =
        (typeof detail === "string" && detail) ||
        (Array.isArray(detail) && detail[0]?.msg) ||
        (res.status === 502 ? "Serwer niedostępny (502) — spróbuj za chwilę lub mniejszą liczbę filmów" : `Error ${res.status}`);
      const err = new Error(msg);
      err.status = res.status;
      throw err;
    }
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

  function syncSiteBranding(b) {
    if (window.YtsBranding && b) window.YtsBranding.apply(b);
  }

  function applyAdminLogo(b, textId, imgId) {
    const name = b.siteName || "YTS";
    const logoText = document.getElementById(textId);
    const logoImg = document.getElementById(imgId);
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

  function applyAdminBranding(b) {
    if (!b) return;
    applyAdminLogo(b, "adminHeadLogoText", "adminHeadLogoImg");
    applyAdminLogo(b, "adminLoginLogoText", "adminLoginLogoImg");
    syncSiteBranding(b);
  }

  async function fetchSiteBranding() {
    return api("/site/branding", { auth: false });
  }

  function renderLogin(app, onSuccess) {
    app.innerHTML = `
      <div class="admin-wrap">
        <div class="admin-card">
          <div class="admin-card__brand">
            <a href="/" class="brand">
              <span class="brand__logo" id="adminLoginLogoText">YTS</span>
              <img class="brand__logo-img" id="adminLoginLogoImg" alt="" hidden />
            </a>
            <h1 class="admin-card__title">Admin Panel</h1>
          </div>
          <form id="adminLoginForm" class="admin-form">
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
          auth: false,
          body: JSON.stringify({
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

    void fetchSiteBranding().then(applyAdminBranding).catch(() => {});
  }

  function renderDashboard(app) {
    const ADMIN_MOVIES_SORT_KEY = "yts_admin_movies_sort";
    let moviesPage = 1;
    let moviesLimit = 50;
    let moviesSortBy = "updated_at";
    let moviesOrder = "desc";
    const savedSort = sessionStorage.getItem(ADMIN_MOVIES_SORT_KEY);
    if (savedSort && savedSort.includes(":")) {
      const [sb, ord] = savedSort.split(":");
      if (sb) moviesSortBy = sb;
      if (ord === "asc" || ord === "desc") moviesOrder = ord;
    }
    const selectedIds = new Set();

    function moviesQuery() {
      return `page=${moviesPage}&limit=${moviesLimit}&sort_by=${encodeURIComponent(moviesSortBy)}&order=${encodeURIComponent(moviesOrder)}`;
    }

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
            <div class="admin-panel__brand">
              <a href="/" class="brand">
                <span class="brand__logo" id="adminHeadLogoText">YTS</span>
                <img class="brand__logo-img" id="adminHeadLogoImg" alt="" hidden />
              </a>
              <span class="admin-panel__subtitle">Admin</span>
            </div>
            <button type="button" class="btn-admin-outline" id="adminLogout">Logout</button>
          </div>

          <div class="admin-stats" id="adminStats">
            <div class="admin-stat admin-stat--live"><span>Teraz online</span><strong id="statActive">—</strong></div>
            <div class="admin-stat"><span>Movies</span><strong id="statCount">—</strong></div>
            <div class="admin-stat"><span>Last scrape</span><strong id="statLast">—</strong></div>
            <div class="admin-stat"><span>Last batch</span><strong id="statBatch">—</strong></div>
            <div class="admin-stat"><span>NEW</span><strong id="statNew">—</strong></div>
          </div>

          <nav class="admin-tabs" id="adminTabs" role="tablist" aria-label="Sekcje panelu">
            <button type="button" class="admin-tabs__btn admin-tabs__btn--active" data-tab="movies" role="tab" aria-selected="true">Filmy</button>
            <button type="button" class="admin-tabs__btn" data-tab="analytics" role="tab" aria-selected="false">Analityka</button>
            <button type="button" class="admin-tabs__btn" data-tab="scraping" role="tab" aria-selected="false">Scraping</button>
            <button type="button" class="admin-tabs__btn" data-tab="branding" role="tab" aria-selected="false">Wygląd</button>
            <button type="button" class="admin-tabs__btn" data-tab="files" role="tab" aria-selected="false">Pliki witryny</button>
          </nav>

          <div class="admin-tabs__panels">
          <section class="admin-tab admin-tab--active admin-section" data-tab="movies" id="adminTabMovies" role="tabpanel">
            <h2>Filmy w bazie</h2>
            <p class="admin-hint">Każdy scraping dopisuje nowe filmy do bazy (istniejące są pomijane). Ostatnio dodane mają NEW do następnego scrapingu.</p>
            <div class="admin-list-toolbar">
              <label>
                Na stronę
                <select id="adminMoviesLimit">
                  <option value="50">50</option>
                  <option value="100">100</option>
                  <option value="200">200</option>
                  <option value="300">300</option>
                  <option value="500">500</option>
                </select>
              </label>
              <label>
                Sortuj
                <select id="adminMoviesSort">
                  <option value="updated_at:desc">Najnowsze scrapowane</option>
                  <option value="updated_at:asc">Najstarsze scrapowane</option>
                  <option value="title:asc">Tytuł A→Z</option>
                  <option value="title:desc">Tytuł Z→A</option>
                  <option value="year:desc">Rok ↓</option>
                  <option value="year:asc">Rok ↑</option>
                  <option value="rating:desc">Rating ↓</option>
                  <option value="rating:asc">Rating ↑</option>
                  <option value="id:desc">ID ↓</option>
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
                    <th>Dodano</th>
                    <th>Slug</th>
                    <th>Akcje</th>
                  </tr>
                </thead>
                <tbody id="adminMoviesBody">
                  <tr><td colspan="8" class="admin-movies-empty">Ładowanie…</td></tr>
                </tbody>
              </table>
            </div>
          </section>

          <section class="admin-tab admin-section" data-tab="analytics" id="adminTabAnalytics" role="tabpanel" hidden>
            <h2>Ruch na stronie</h2>
            <p class="admin-hint">Własna analityka — ping co 30 s z przeglądarki. Aktywny = ostatni ping w ciągu 90 s (boty pomijane).</p>
            <div class="admin-stats admin-stats--analytics" id="adminAnalyticsStats">
              <div class="admin-stat admin-stat--live"><span>Teraz online</span><strong id="anActive">—</strong></div>
              <div class="admin-stat"><span>Odsłony dziś</span><strong id="anViews">—</strong></div>
              <div class="admin-stat"><span>Unikalni dziś</span><strong id="anUnique">—</strong></div>
              <div class="admin-stat"><span>Szczyt dziś</span><strong id="anPeak">—</strong></div>
              <div class="admin-stat"><span>Śr. czas wizyty</span><strong id="anAvg">—</strong></div>
            </div>

            <h3 class="admin-tab__subtitle">Okresy</h3>
            <div class="admin-analytics-periods" id="anPeriodTabs" role="tablist" aria-label="Zakres statystyk">
              <button type="button" class="admin-analytics-periods__btn admin-analytics-periods__btn--active" data-days="3">3 dni</button>
              <button type="button" class="admin-analytics-periods__btn" data-days="7">7 dni</button>
              <button type="button" class="admin-analytics-periods__btn" data-days="30">30 dni</button>
            </div>
            <div class="admin-stats admin-stats--analytics" id="adminAnalyticsPeriodStats">
              <div class="admin-stat"><span>Odsłony</span><strong id="anPeriodViews">—</strong></div>
              <div class="admin-stat"><span>Unikalni</span><strong id="anPeriodUnique">—</strong></div>
              <div class="admin-stat"><span>Szczyt online</span><strong id="anPeriodPeak">—</strong></div>
              <div class="admin-stat"><span>Śr. czas wizyty</span><strong id="anPeriodAvg">—</strong></div>
            </div>

            <div class="admin-charts" id="adminAnalyticsCharts">
              <div class="admin-chart">
                <div class="admin-chart__head">
                  <span class="admin-chart__title">Odsłony</span>
                  <span class="admin-chart__hint" id="anChartViewsHint"></span>
                </div>
                <svg class="admin-chart__svg" id="anChartViews" viewBox="0 0 640 180" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Wykres odsłon"></svg>
              </div>
              <div class="admin-chart">
                <div class="admin-chart__head">
                  <span class="admin-chart__title">Unikalni użytkownicy</span>
                  <span class="admin-chart__hint" id="anChartUniqueHint"></span>
                </div>
                <svg class="admin-chart__svg admin-chart__svg--line" id="anChartUnique" viewBox="0 0 640 180" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Wykres unikalnych użytkowników"></svg>
              </div>
              <div class="admin-chart">
                <div class="admin-chart__head">
                  <span class="admin-chart__title">Szczyt online</span>
                  <span class="admin-chart__hint" id="anChartPeakHint"></span>
                </div>
                <svg class="admin-chart__svg" id="anChartPeak" viewBox="0 0 640 180" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Wykres szczytu online"></svg>
              </div>
            </div>

            <h3 class="admin-tab__subtitle">Tabela dzienna</h3>
            <div class="admin-analytics-table-wrap">
              <table class="admin-analytics" id="anDailyTable">
                <thead>
                  <tr><th>Dzień</th><th>Odsłony</th><th>Unikalni</th><th>Szczyt online</th></tr>
                </thead>
                <tbody id="anDailyTableBody">
                  <tr><td colspan="4" class="admin-movies-empty">Ładowanie…</td></tr>
                </tbody>
              </table>
            </div>

            <h3 class="admin-tab__subtitle">Kraje</h3>
            <p class="admin-hint" id="anCountriesHint">Odsłony wg kraju w wybranym okresie (UTC). Kraj z Cloudflare lub geolokalizacji IP.</p>
            <div class="admin-analytics-table-wrap">
              <table class="admin-analytics admin-analytics--countries" id="anCountriesTable">
                <thead>
                  <tr><th></th><th>Kraj</th><th>Odsłony</th><th>Udział</th></tr>
                </thead>
                <tbody id="anCountriesBody">
                  <tr><td colspan="4" class="admin-movies-empty">Ładowanie…</td></tr>
                </tbody>
              </table>
            </div>

            <h3 class="admin-tab__subtitle">Aktywne strony</h3>
            <table class="admin-analytics" id="adminAnalyticsPages">
              <thead>
                <tr><th>Ścieżka</th><th>Osoby</th></tr>
              </thead>
              <tbody id="adminAnalyticsPagesBody">
                <tr><td colspan="2" class="admin-movies-empty">Ładowanie…</td></tr>
              </tbody>
            </table>
          </section>

          <section class="admin-tab admin-section" data-tab="scraping" id="adminTabScraping" role="tabpanel" hidden>
            <h2>Scrape from YTS</h2>
            <p class="admin-hint">Skanuj: równolegle po 8 stronach, z przeskokiem przez bloki duplikatów. Potem Pobierz.</p>
            <div class="admin-scrape-status" id="scrapeStatusPanel">
              <div class="admin-stats admin-stats--scrape">
                <div class="admin-stat"><span>W kolejce</span><strong id="scrapeStatPending">—</strong></div>
                <div class="admin-stat"><span>Przeskan. stron</span><strong id="scrapeStatPages">—</strong></div>
                <div class="admin-stat"><span>Nast. str. YTS</span><strong id="scrapeStatResume">—</strong></div>
                <div class="admin-stat"><span>W bazie</span><strong id="scrapeStatDb">—</strong></div>
              </div>
              <p class="admin-hint" id="scrapeLastScanMeta">Ostatni skan: —</p>
              <ul class="admin-scrape-queue" id="scrapeQueueList" hidden></ul>
            </div>
            <form id="scrapeForm" class="admin-scrape">
              <label>
                Liczba filmów
                <input type="number" id="scrapeCount" min="1" value="10" />
              </label>
              <button type="button" class="btn-admin-outline" id="scrapeScanBtn">Skanuj</button>
              <button type="submit" class="btn-browse" id="scrapeBtn">Pobierz</button>
            </form>
            <pre class="admin-log" id="adminLog">Ready.</pre>

            <h2 class="admin-tab__subtitle">Auto scraping</h2>
            <p class="admin-hint">Ten sam skaner co ręczny — wspólna kolejna strona YTS; auto robi krótsze cykle (50 str. / interwał).</p>
            <form id="autoScrapeForm" class="admin-scrape admin-scrape--auto">
              <label class="admin-check">
                <input type="checkbox" id="autoScrapeEnabled" />
                Włączone
              </label>
              <label>
                Co ile minut
                <input type="number" id="autoScrapeInterval" min="2" max="1440" value="60" />
              </label>
              <label>
                Filmów na cykl
                <input type="number" id="autoScrapeCount" min="1" value="10" />
              </label>
              <button type="submit" class="btn-browse" id="autoScrapeSave">Zapisz</button>
            </form>
            <div class="admin-auto-status" id="autoScrapeStatus">Ładowanie statusu…</div>
          </section>

          <section class="admin-tab admin-section" data-tab="branding" id="adminTabBranding" role="tabpanel" hidden>
            <h2>Wygląd witryny</h2>
            <p class="admin-hint">Logo i tagline w nagłówku strony. Logo tekstowe używa nazwy witryny — możesz też wgrać obrazek (PNG, JPG, WEBP, SVG).</p>
            <form id="adminBrandingForm" class="admin-branding">
              <div class="admin-branding__preview" id="adminBrandingPreview">
                <span class="brand__logo" id="adminPreviewLogoText">YTS</span>
                <img class="brand__logo-img" id="adminPreviewLogoImg" alt="" hidden />
                <span class="brand__tag" id="adminPreviewTagline">HD movies at the smallest file size</span>
              </div>
              <label>
                Nazwa witryny (tekst logo)
                <input type="text" id="adminSiteName" maxlength="40" placeholder="YTS" />
              </label>
              <label>
                Tagline pod logo
                <input type="text" id="adminSiteTagline" maxlength="120" placeholder="HD movies at the smallest file size" />
              </label>
              <div class="admin-branding__logo">
                <label>
                  Logo (obrazek)
                  <input type="file" id="adminLogoFile" accept=".png,.jpg,.jpeg,.webp,.svg,.gif" />
                </label>
                <button type="button" class="btn-admin-outline" id="adminLogoUpload">Wgraj logo</button>
                <button type="button" class="btn-admin-delete" id="adminLogoRemove" hidden>Usuń logo</button>
              </div>
              <button type="submit" class="btn-browse">Zapisz wygląd</button>
            </form>
          </section>

          <section class="admin-tab admin-section" data-tab="files" id="adminTabFiles" role="tabpanel" hidden>
            <h2>Pliki witryny</h2>
            <p class="admin-hint">Pliki w katalogu głównym witryny (weryfikacja Google/Bing, <code>sw.js</code>, <code>manifest.json</code>). Adres: <code>https://twoja-domena/BingSiteAuth.xml</code> — <strong>bez</strong> <code>/files/</code>. Chronione: <code>index.html</code>, katalogi <code>js/</code> i <code>css/</code>.</p>
            <div class="admin-files-toolbar">
              <button type="button" class="btn-admin-outline" id="adminFilesRefresh">Odśwież</button>
            </div>
            <div class="admin-files-create">
              <h3>Nowy plik</h3>
              <form id="adminFileCreateForm" class="admin-file-form">
                <label>
                  Nazwa pliku
                  <input type="text" id="adminFileName" placeholder="sw.js lub manifest.webmanifest" pattern="[A-Za-z0-9._-]+" required />
                </label>
                <label>
                  Treść
                  <textarea id="adminFileContent" rows="5" placeholder="google-site-verification: google123abc.html"></textarea>
                </label>
                <button type="submit" class="btn-browse">Utwórz plik</button>
              </form>
              <form id="adminFileUploadForm" class="admin-file-form">
                <h3>Upload pliku</h3>
                <label>
                  Nazwa na serwerze
                  <input type="text" id="adminUploadName" placeholder="BingSiteAuth.xml" pattern="[A-Za-z0-9._-]+" />
                </label>
                <label>
                  Plik
                  <input type="file" id="adminUploadFile" accept=".html,.htm,.txt,.xml,.json,.js,.webmanifest" required />
                </label>
                <button type="submit" class="btn-browse">Wyślij plik</button>
              </form>
            </div>
            <div class="admin-files-wrap">
              <table class="admin-files" id="adminFilesTable">
                <thead>
                  <tr>
                    <th>Plik</th>
                    <th>Rozmiar</th>
                    <th>Zmieniony</th>
                    <th>Akcje</th>
                  </tr>
                </thead>
                <tbody id="adminFilesBody">
                  <tr><td colspan="4" class="admin-movies-empty">Ładowanie…</td></tr>
                </tbody>
              </table>
            </div>
            <div class="admin-file-editor" id="adminFileEditor" hidden>
              <h3>Edycja: <span id="adminFileEditorName"></span></h3>
              <textarea id="adminFileEditorContent" rows="8"></textarea>
              <div class="admin-file-editor__actions">
                <button type="button" class="btn-browse" id="adminFileEditorSave">Zapisz</button>
                <button type="button" class="btn-admin-outline" id="adminFileEditorCancel">Anuluj</button>
              </div>
            </div>
          </section>
          </div>
        </div>
      </div>`;

    document.getElementById("adminLogout").addEventListener("click", async () => {
      clearAllAdminTimers();
      try {
        await api("/admin/logout", { method: "POST" });
      } catch {
        /* cookie may already be gone */
      }
      clearToken();
      window.YtsAdmin.render(app);
    });

    const ADMIN_TAB_KEY = "yts_admin_tab";
    const validTabs = new Set(["movies", "analytics", "scraping", "branding", "files"]);
    const SCRAPE_POLL_MS = 3000;
    const SCRAPE_POLL_ACTIVE_MS = 2000;
    const ANALYTICS_POLL_MS = 10000;
    let scrapePollFast = false;

    async function refreshScrapePanel() {
      if (scrapePollInFlight) return;
      scrapePollInFlight = true;
      try {
        await Promise.all([loadScrapeQueue(), loadAutoScrape()]);
      } finally {
        scrapePollInFlight = false;
      }
    }

    function scheduleScrapePoll(delayMs) {
      clearScrapePollTimer();
      scrapePollTimer = window.setTimeout(async () => {
        if ((sessionStorage.getItem(ADMIN_TAB_KEY) || "movies") !== "scraping") {
          clearScrapePollTimer();
          return;
        }
        await refreshScrapePanel();
        scheduleScrapePoll(scrapePollFast ? SCRAPE_POLL_ACTIVE_MS : SCRAPE_POLL_MS);
      }, delayMs);
    }

    function startScrapePollTimer(intervalMs = SCRAPE_POLL_MS) {
      scrapePollFast = intervalMs <= SCRAPE_POLL_ACTIVE_MS;
      void refreshScrapePanel();
      scheduleScrapePoll(intervalMs);
    }

    function stopScrapePollTimer() {
      clearScrapePollTimer();
    }

    function startAnalyticsPollTimer() {
      clearAnalyticsPollTimer();
      void loadAnalytics();
      analyticsPollTimer = window.setInterval(() => {
        if ((sessionStorage.getItem(ADMIN_TAB_KEY) || "movies") !== "analytics") {
          clearAnalyticsPollTimer();
          return;
        }
        void loadAnalytics();
      }, ANALYTICS_POLL_MS);
    }

    function stopAnalyticsPollTimer() {
      clearAnalyticsPollTimer();
    }

    function switchTab(name) {
      if (!validTabs.has(name)) name = "movies";
      document.querySelectorAll(".admin-tabs__btn").forEach((btn) => {
        const active = btn.dataset.tab === name;
        btn.classList.toggle("admin-tabs__btn--active", active);
        btn.setAttribute("aria-selected", active ? "true" : "false");
      });
      document.querySelectorAll(".admin-tab").forEach((panel) => {
        const active = panel.dataset.tab === name;
        panel.hidden = !active;
        panel.classList.toggle("admin-tab--active", active);
      });
      sessionStorage.setItem(ADMIN_TAB_KEY, name);
      if (name === "files") loadFiles();
      if (name === "branding") loadBranding();
      if (name === "scraping") {
        startScrapePollTimer(SCRAPE_POLL_MS);
      } else {
        stopScrapePollTimer();
      }
      if (name === "analytics") {
        startAnalyticsPollTimer();
      } else {
        stopAnalyticsPollTimer();
      }
    }

    document.getElementById("adminTabs").addEventListener("click", (e) => {
      const btn = e.target.closest(".admin-tabs__btn");
      if (!btn) return;
      switchTab(btn.dataset.tab);
    });

    const initialTab = sessionStorage.getItem(ADMIN_TAB_KEY) || "movies";
    switchTab(validTabs.has(initialTab) ? initialTab : "movies");

    document.getElementById("adminMoviesLimit").value = String(moviesLimit);
    document.getElementById("adminMoviesSort").value = `${moviesSortBy}:${moviesOrder}`;
    document.getElementById("adminMoviesLimit").addEventListener("change", (e) => {
      moviesLimit = parseInt(e.target.value, 10) || 50;
      moviesPage = 1;
      loadMovies();
    });
    document.getElementById("adminMoviesSort").addEventListener("change", (e) => {
      const [sb, ord] = (e.target.value || "updated_at:desc").split(":");
      moviesSortBy = sb || "updated_at";
      moviesOrder = ord === "asc" ? "asc" : "desc";
      sessionStorage.setItem(ADMIN_MOVIES_SORT_KEY, `${moviesSortBy}:${moviesOrder}`);
      moviesPage = 1;
      loadMovies();
    });

    function updateBrandingPreview(b) {
      const tag = b.siteTagline || "HD movies at the smallest file size";
      const tagEl = document.getElementById("adminPreviewTagline");
      const removeBtn = document.getElementById("adminLogoRemove");

      applyAdminBranding(b);
      applyAdminLogo(b, "adminPreviewLogoText", "adminPreviewLogoImg");
      if (tagEl) tagEl.textContent = tag;
      if (removeBtn) removeBtn.hidden = !(b.logoType === "image" && b.logoUrl);
    }

    async function loadBranding() {
      try {
        const b = await api("/admin/branding");
        document.getElementById("adminSiteName").value = b.siteName || "";
        document.getElementById("adminSiteTagline").value = b.siteTagline || "";
        updateBrandingPreview(b);
      } catch (err) {
        console.error(err);
      }
    }

    document.getElementById("adminBrandingForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const b = await api("/admin/branding", {
          method: "POST",
          body: JSON.stringify({
            site_name: document.getElementById("adminSiteName").value.trim(),
            site_tagline: document.getElementById("adminSiteTagline").value.trim(),
          }),
        });
        updateBrandingPreview(b);
        alert("Zapisano.");
      } catch (err) {
        alert(err.message);
      }
    });

    document.getElementById("adminLogoUpload").addEventListener("click", async () => {
      const fileInput = document.getElementById("adminLogoFile");
      const file = fileInput.files && fileInput.files[0];
      if (!file) {
        alert("Wybierz plik logo.");
        return;
      }
      const form = new FormData();
      form.append("file", file);
      try {
        const b = await api("/admin/branding/logo", { method: "POST", body: form });
        fileInput.value = "";
        updateBrandingPreview(b);
        alert("Logo wgrane.");
      } catch (err) {
        alert(err.message);
      }
    });

    document.getElementById("adminLogoRemove").addEventListener("click", async () => {
      if (!confirm("Usunąć logo i wrócić do tekstu?")) return;
      try {
        const b = await api("/admin/branding/logo", { method: "DELETE" });
        updateBrandingPreview(b);
      } catch (err) {
        alert(err.message);
      }
    });

    document.getElementById("adminSiteName").addEventListener("input", () => {
      updateBrandingPreview({
        siteName: document.getElementById("adminSiteName").value,
        siteTagline: document.getElementById("adminSiteTagline").value,
        logoType: document.getElementById("adminPreviewLogoImg").hidden ? "text" : "image",
        logoUrl: document.getElementById("adminPreviewLogoImg").src || "",
      });
    });

    document.getElementById("adminSiteTagline").addEventListener("input", () => {
      document.getElementById("adminPreviewTagline").textContent =
        document.getElementById("adminSiteTagline").value || "HD movies at the smallest file size";
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

    function formatFileSize(bytes) {
      if (bytes < 1024) return `${bytes} B`;
      if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }

    let editingFilePath = "";

    async function loadFiles() {
      const tbody = document.getElementById("adminFilesBody");
      try {
        const data = await api("/admin/files");
        const files = data.files || [];
        if (!files.length) {
          tbody.innerHTML = `<tr><td colspan="4" class="admin-movies-empty">Brak plików w katalogu głównym.</td></tr>`;
          return;
        }
        tbody.innerHTML = files
          .map(
            (f) => `
          <tr>
            <td class="admin-files__path">
              <a href="${escapeAttr(f.url)}" target="_blank" rel="noopener">${escapeHtml(f.path)}</a>
            </td>
            <td>${formatFileSize(f.size)}</td>
            <td>${formatAdminTime(f.modified_at)}</td>
            <td class="admin-movies__actions">
              ${f.editable && !f.protected ? `<button type="button" class="btn-admin-outline btn-file-edit" data-path="${escapeAttr(f.path)}">Edytuj</button>` : ""}
              ${f.protected ? "" : `<button type="button" class="btn-admin-delete btn-file-delete" data-path="${escapeAttr(f.path)}">Usuń</button>`}
            </td>
          </tr>`
          )
          .join("");
      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="4" class="admin-movies-empty">Błąd: ${escapeHtml(err.message)}</td></tr>`;
      }
    }

    document.getElementById("adminFilesRefresh").addEventListener("click", loadFiles);

    document.getElementById("adminFileCreateForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const path = document.getElementById("adminFileName").value.trim();
      const content = document.getElementById("adminFileContent").value;
      try {
        await api("/admin/files", {
          method: "PUT",
          body: JSON.stringify({ path, content, overwrite: false }),
        });
        document.getElementById("adminFileName").value = "";
        document.getElementById("adminFileContent").value = "";
        loadFiles();
      } catch (err) {
        alert(err.message);
      }
    });

    document.getElementById("adminFileUploadForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fileInput = document.getElementById("adminUploadFile");
      const file = fileInput.files && fileInput.files[0];
      if (!file) return;
      const customName = document.getElementById("adminUploadName").value.trim();
      const path = customName || file.name;
      const form = new FormData();
      form.append("path", path);
      form.append("file", file);
      form.append("overwrite", "true");
      try {
        await api("/admin/files/upload", { method: "POST", body: form });
        fileInput.value = "";
        document.getElementById("adminUploadName").value = "";
        loadFiles();
      } catch (err) {
        alert(err.message);
      }
    });

    document.getElementById("adminFilesBody").addEventListener("click", async (e) => {
      const editBtn = e.target.closest(".btn-file-edit");
      const deleteBtn = e.target.closest(".btn-file-delete");
      if (editBtn) {
        const path = editBtn.dataset.path;
        try {
          const data = await api(`/admin/files/content?path=${encodeURIComponent(path)}`);
          if (data.binary) {
            alert("Ten plik nie jest tekstowy — użyj uploadu zamiast edycji.");
            return;
          }
          editingFilePath = path;
          document.getElementById("adminFileEditorName").textContent = path;
          document.getElementById("adminFileEditorContent").value = data.content || "";
          document.getElementById("adminFileEditor").hidden = false;
        } catch (err) {
          alert(err.message);
        }
        return;
      }
      if (deleteBtn) {
        const path = deleteBtn.dataset.path;
        if (!confirm(`Usunąć plik ${path}?`)) return;
        deleteBtn.disabled = true;
        try {
          await api(`/admin/files?path=${encodeURIComponent(path)}`, { method: "DELETE" });
          if (editingFilePath === path) {
            editingFilePath = "";
            document.getElementById("adminFileEditor").hidden = true;
          }
          loadFiles();
        } catch (err) {
          alert(err.message);
        } finally {
          deleteBtn.disabled = false;
        }
      }
    });

    document.getElementById("adminFileEditorSave").addEventListener("click", async () => {
      if (!editingFilePath) return;
      const btn = document.getElementById("adminFileEditorSave");
      btn.disabled = true;
      try {
        await api("/admin/files", {
          method: "PUT",
          body: JSON.stringify({
            path: editingFilePath,
            content: document.getElementById("adminFileEditorContent").value,
            overwrite: true,
          }),
        });
        document.getElementById("adminFileEditor").hidden = true;
        editingFilePath = "";
        loadFiles();
      } catch (err) {
        alert(err.message);
      } finally {
        btn.disabled = false;
      }
    });

    document.getElementById("adminFileEditorCancel").addEventListener("click", () => {
      editingFilePath = "";
      document.getElementById("adminFileEditor").hidden = true;
    });

    function formatLastScan(scan) {
      if (!scan) return "";
      const mode = scan.mode === "auto" ? "auto" : "ręczny";
      let line = `Ostatni skan (${mode}): +${scan.saved ?? 0}`;
      if (scan.candidates_found) line += `, znaleziono ${scan.candidates_found}`;
      if (scan.pages_scanned) line += `, ${scan.pages_scanned} str.`;
      if (scan.start_page) line += ` od ${scan.start_page}`;
      if (scan.resume_page) line += ` → nast. ${scan.resume_page}`;
      return line;
    }

    function formatAutoStatus(s) {
      const lines = [];
      lines.push(s.enabled ? "Status: włączone" : "Status: wyłączone");
      if (s.scrape_resume_page) {
        lines.push(`Kolejna strona YTS: ${s.scrape_resume_page}`);
      }
      if (s.scrape_queue?.pending_count) {
        lines.push(`Kolejka ręczna: ${s.scrape_queue.pending_count}`);
      }
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
        else {
          let msg = `Ostatni wynik: +${r.saved ?? 0}`;
          if (r.skipped) msg += `, pominięto ${r.skipped}`;
          if (r.pages_scanned) msg += ` (${r.pages_scanned} str.)`;
          if (r.start_page) msg += `, od str. ${r.start_page}`;
          if (r.resume_page) msg += ` → nast. ${r.resume_page}`;
          const inDb = s.movies_in_db ?? r.total_in_db;
          msg += ` (w bazie: ${inDb ?? "?"})`;
          if ((r.saved ?? 0) === 0 && r.pages_scanned) {
            msg += " — w tym zakresie stron brak nowych, auto idzie dalej";
          }
          if (r.detail_errors) msg += `, pominięto ${r.detail_errors} (błąd YTS)`;
          lines.push(msg);
        }
      } else if (s.movies_in_db != null) {
        lines.push(`W bazie: ${s.movies_in_db}`);
      }
      const scanLine = formatLastScan(s.scrape_last_scan);
      if (scanLine) lines.push(scanLine);
      return lines.join(" · ");
    }

    async function loadAutoScrape() {
      const statusEl = document.getElementById("autoScrapeStatus");
      try {
        const s = await api("/admin/auto-scrape");
        scrapePollFast = scrapePollFast || !!s.running;
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

    async function applyStats(s) {
      const activeEl = document.getElementById("statActive");
      if (activeEl) activeEl.textContent = s.active_now != null ? String(s.active_now) : "—";
      document.getElementById("statCount").textContent = s.movies_count;
      document.getElementById("statLast").textContent = s.last_scrape || "never";
      document.getElementById("statBatch").textContent = s.last_scrape_count || "—";
      document.getElementById("statNew").textContent = s.new_count ?? "—";
    }

    function formatDuration(sec) {
      const n = Math.max(0, parseInt(sec, 10) || 0);
      if (n < 60) return `${n} s`;
      const m = Math.floor(n / 60);
      const s = n % 60;
      return s ? `${m} min ${s} s` : `${m} min`;
    }

    const ANALYTICS_PERIOD_KEY = "yts_admin_analytics_period";
    let analyticsCache = null;
    let analyticsPeriodDays = parseInt(sessionStorage.getItem(ANALYTICS_PERIOD_KEY) || "3", 10);
    if (![3, 7, 30].includes(analyticsPeriodDays)) analyticsPeriodDays = 3;

    let countryNames = null;
    function getCountryName(code) {
      if (!code || code === "UN") return "Nieznany";
      try {
        if (!countryNames) countryNames = new Intl.DisplayNames(["pl"], { type: "region" });
        return countryNames.of(code) || code;
      } catch {
        return code;
      }
    }

    function countryFlag(code) {
      if (!code || code === "UN" || code.length !== 2) return "🌐";
      const c = code.toUpperCase();
      return String.fromCodePoint(...[...c].map((ch) => 127397 + ch.charCodeAt(0)));
    }

    function formatChartDay(day, full) {
      if (!day) return "";
      const parts = String(day).split("-");
      if (parts.length !== 3) return day;
      return full ? `${parts[2]}.${parts[1]}.${parts[0]}` : `${parts[2]}.${parts[1]}`;
    }

    function chartLayout() {
      const w = 640;
      const h = 180;
      const padL = 44;
      const padR = 12;
      const padT = 16;
      const padB = 32;
      return { w, h, padL, padR, padT, padB, chartW: w - padL - padR, chartH: h - padT - padB };
    }

    function renderChartYAxis(max, layout) {
      const { padL, padR, padT, chartH, w } = layout;
      const ticks = [0];
      if (max > 1) ticks.push(Math.ceil(max / 2));
      if (max > 0) ticks.push(max);
      const unique = [...new Set(ticks)].sort((a, b) => a - b);
      return unique
        .map((t) => {
          const y = padT + chartH - (t / max) * chartH;
          return `
            <line x1="${padL}" y1="${y.toFixed(1)}" x2="${w - padR}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,0.08)" />
            <text x="${padL - 6}" y="${(y + 3).toFixed(1)}" fill="#9aa0a6" font-size="10" text-anchor="end">${t}</text>`;
        })
        .join("");
    }

    function renderBarChart(svgEl, series, key, color) {
      if (!svgEl || !series.length) return;
      const values = series.map((d) => Number(d[key]) || 0);
      const max = Math.max(1, ...values);
      const layout = chartLayout();
      const { w, h, padL, padT, chartW, chartH } = layout;
      const barW = chartW / series.length;
      const fontSize = series.length > 14 ? 8 : series.length > 9 ? 9 : 10;
      const showAllDates = series.length <= 10;

      const bars = values
        .map((v, i) => {
          const bh = Math.max(v > 0 ? 2 : 0, (v / max) * chartH);
          const x = padL + i * barW + 1;
          const y = padT + chartH - bh;
          const width = Math.max(2, barW - 2);
          const cx = x + width / 2;
          const valY = Math.max(padT + 10, y - 4);
          const dateY = h - 6;
          const dateLabel = showAllDates || i === 0 || i === series.length - 1 || i % Math.ceil(series.length / 8) === 0
            ? `<text x="${cx.toFixed(1)}" y="${dateY}" fill="#9aa0a6" font-size="9" text-anchor="middle">${formatChartDay(series[i].day)}</text>`
            : "";
          const valueLabel = `<text x="${cx.toFixed(1)}" y="${valY.toFixed(1)}" fill="#e8eaed" font-size="${fontSize}" font-weight="700" text-anchor="middle">${v}</text>`;
          return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${width.toFixed(1)}" height="${bh.toFixed(1)}" fill="${color}" rx="2" opacity="0.92" />${valueLabel}${dateLabel}`;
        })
        .join("");

      svgEl.innerHTML = `${renderChartYAxis(max, layout)}${bars}`;
    }

    function renderLineChart(svgEl, series, key, color) {
      if (!svgEl || !series.length) return;
      const values = series.map((d) => Number(d[key]) || 0);
      const max = Math.max(1, ...values);
      const layout = chartLayout();
      const { w, h, padL, padT, chartW, chartH } = layout;
      const step = series.length > 1 ? chartW / (series.length - 1) : 0;
      const fontSize = series.length > 14 ? 8 : series.length > 9 ? 9 : 10;
      const showAllDates = series.length <= 10;

      const points = values.map((v, i) => {
        const x = padL + i * step;
        const y = padT + chartH - (v / max) * chartH;
        return { x, y, v, day: series[i].day };
      });

      const polyline = points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
      const markers = points
        .map((p, i) => {
          const dateLabel = showAllDates || i === 0 || i === points.length - 1 || i % Math.ceil(points.length / 8) === 0
            ? `<text x="${p.x.toFixed(1)}" y="${h - 6}" fill="#9aa0a6" font-size="9" text-anchor="middle">${formatChartDay(p.day)}</text>`
            : "";
          const valY = Math.max(padT + 10, p.y - 6);
          return `
            <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4" fill="${color}" stroke="#1a1d21" stroke-width="1.5" />
            <text x="${p.x.toFixed(1)}" y="${valY.toFixed(1)}" fill="#e8eaed" font-size="${fontSize}" font-weight="700" text-anchor="middle">${p.v}</text>
            ${dateLabel}`;
        })
        .join("");

      svgEl.innerHTML = `${renderChartYAxis(max, layout)}<polyline fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" points="${polyline}" opacity="0.95"/>${markers}`;
    }

    function renderDailyTable(series) {
      const tbody = document.getElementById("anDailyTableBody");
      if (!tbody) return;
      if (!series.length) {
        tbody.innerHTML = `<tr><td colspan="4" class="admin-movies-empty">Brak danych w wybranym okresie.</td></tr>`;
        return;
      }
      const rows = [...series].reverse();
      tbody.innerHTML = rows
        .map((d) => {
          const views = Number(d.page_views) || 0;
          const unique = Number(d.unique_visitors) || 0;
          const peak = Number(d.peak_online) || 0;
          const empty = views === 0 && unique === 0 && peak === 0;
          return `<tr class="${empty ? "admin-analytics__row--empty" : ""}">
            <td>${formatChartDay(d.day, true)}</td>
            <td>${views}</td>
            <td>${unique}</td>
            <td>${peak}</td>
          </tr>`;
        })
        .join("");
    }

    function renderCountriesTable(countries) {
      const tbody = document.getElementById("anCountriesBody");
      if (!tbody) return;
      const list = Array.isArray(countries) ? countries : [];
      if (!list.length) {
        tbody.innerHTML = `<tr><td colspan="4" class="admin-movies-empty">Brak danych o krajach w wybranym okresie.</td></tr>`;
        return;
      }
      const total = list.reduce((sum, c) => sum + (Number(c.page_views) || 0), 0) || 1;
      tbody.innerHTML = list
        .map((c) => {
          const code = String(c.country_code || "UN");
          const views = Number(c.page_views) || 0;
          const share = ((views / total) * 100).toFixed(1);
          return `<tr>
            <td class="admin-analytics__flag" title="${escapeAttr(code)}">${countryFlag(code)}</td>
            <td>${escapeHtml(getCountryName(code))} <span class="admin-analytics__code">${escapeHtml(code)}</span></td>
            <td>${views}</td>
            <td>${share}%</td>
          </tr>`;
        })
        .join("");
    }

    function sliceDailySeries(daily, days) {
      const list = Array.isArray(daily) ? daily : [];
      if (list.length <= days) return list;
      return list.slice(list.length - days);
    }

    function applyAnalyticsPeriod(days) {
      if (!analyticsCache) return;
      const period = (analyticsCache.periods || {})[String(days)] || {};
      const series = sliceDailySeries(analyticsCache.daily, days);
      const set = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
      };
      set("anPeriodViews", period.page_views != null ? String(period.page_views) : "—");
      set("anPeriodUnique", period.unique_visitors != null ? String(period.unique_visitors) : "—");
      set("anPeriodPeak", period.peak_online != null ? String(period.peak_online) : "—");
      set("anPeriodAvg", period.avg_duration_seconds != null ? formatDuration(period.avg_duration_seconds) : "—");

      const hint = `ostatnie ${days} dni (UTC)`;
      ["anChartViewsHint", "anChartUniqueHint", "anChartPeakHint"].forEach((id) => set(id, hint));

      renderBarChart(document.getElementById("anChartViews"), series, "page_views", "#6ac045");
      renderLineChart(document.getElementById("anChartUnique"), series, "unique_visitors", "#5eb8ff");
      renderBarChart(document.getElementById("anChartPeak"), series, "peak_online", "#e8b84a");
      renderDailyTable(series);
      renderCountriesTable((analyticsCache.countries || {})[String(days)] || []);

      document.querySelectorAll(".admin-analytics-periods__btn").forEach((btn) => {
        const active = parseInt(btn.dataset.days, 10) === days;
        btn.classList.toggle("admin-analytics-periods__btn--active", active);
      });
    }

    function applyAnalytics(a) {
      analyticsCache = a;
      const active = a.active_now != null ? String(a.active_now) : "—";
      const activeHeader = document.getElementById("statActive");
      if (activeHeader) activeHeader.textContent = active;
      const set = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
      };
      set("anActive", active);
      set("anViews", a.today_page_views != null ? String(a.today_page_views) : "—");
      set("anUnique", a.today_unique != null ? String(a.today_unique) : "—");
      set("anPeak", a.peak_today != null ? String(a.peak_today) : "—");
      set("anAvg", a.avg_duration_seconds != null ? formatDuration(a.avg_duration_seconds) : "—");

      applyAnalyticsPeriod(analyticsPeriodDays);

      const tbody = document.getElementById("adminAnalyticsPagesBody");
      if (!tbody) return;
      const pages = a.active_pages || [];
      if (!pages.length) {
        tbody.innerHTML = `<tr><td colspan="2" class="admin-movies-empty">Nikogo aktywnego na stronie.</td></tr>`;
        return;
      }
      tbody.innerHTML = pages
        .map(
          (p) =>
            `<tr><td class="admin-analytics__path">${escapeHtml(p.path || "/")}</td><td>${p.count}</td></tr>`
        )
        .join("");
    }

    document.getElementById("anPeriodTabs")?.addEventListener("click", (e) => {
      const btn = e.target.closest(".admin-analytics-periods__btn");
      if (!btn) return;
      const days = parseInt(btn.dataset.days, 10);
      if (![3, 7, 30].includes(days)) return;
      analyticsPeriodDays = days;
      sessionStorage.setItem(ANALYTICS_PERIOD_KEY, String(days));
      applyAnalyticsPeriod(days);
    });

    async function loadAnalytics() {
      try {
        const a = await api("/admin/analytics");
        applyAnalytics(a);
      } catch (err) {
        if (isAuthError(err)) {
          clearToken();
          window.YtsAdmin.render(app);
        }
      }
    }

    function renderMoviesTable(data) {
      const tbody = document.getElementById("adminMoviesBody");
      const movies = data.movies || [];
      document.getElementById("adminMoviesMeta").textContent =
        `Strona ${data.page}/${data.total_pages} · ${data.movie_count} filmów`;
      renderMoviesPagination(data);
      if (!movies.length) {
        tbody.innerHTML = `<tr><td colspan="8" class="admin-movies-empty">Brak filmów w bazie.</td></tr>`;
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
            <td class="admin-movies__date">${m.updated_at ? formatAdminTime(m.updated_at) : "—"}</td>
            <td class="admin-movies__slug">${escapeHtml(m.slug || "—")}</td>
            <td class="admin-movies__actions">
              <a class="admin-movies__link" href="${escapeHtml(m.url)}" target="_blank" rel="noopener">Podgląd</a>
              <button type="button" class="btn-admin-delete" data-id="${m.id}" data-title="${escapeAttr(m.title || "")}">Usuń</button>
            </td>
          </tr>`
        )
        .join("");
      updateBulkBar();
    }

    async function refreshAdminData() {
      void loadMovies();
      void loadStats();
    }

    function initAdminData() {
      void loadMovies();
      window.setTimeout(() => void loadStats(), 0);
    }

    async function loadStats() {
      try {
        const s = await api("/admin/stats");
        applyStats(s);
      } catch (err) {
        if (isAuthError(err)) {
          clearToken();
          window.YtsAdmin.render(app);
        }
      }
    }

    async function loadMovies() {
      const tbody = document.getElementById("adminMoviesBody");
      try {
        const data = await api(`/admin/movies?${moviesQuery()}`);
        renderMoviesTable(data);
      } catch (err) {
        if (isAuthError(err)) {
          clearToken();
          window.YtsAdmin.render(app);
          return;
        }
        tbody.innerHTML = `<tr><td colspan="8" class="admin-movies-empty">Błąd: ${escapeHtml(err.message)}</td></tr>`;
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
        refreshAdminData();
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
        refreshAdminData();
      } catch (err) {
        alert(err.message);
        btn.disabled = false;
      }
    });

    async function loadScrapeQueue() {
      const set = (id, text) => {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
      };
      try {
        const s = await api("/admin/scrape/queue");
        const pending = s.pending_count || 0;
        const meta = s.queue_meta || {};
        const pages = meta.pages_scanned ?? s.last_scan?.pages_scanned;
        set("scrapeStatPending", String(pending));
        set("scrapeStatPages", pages != null ? String(pages) : "—");
        set("scrapeStatResume", s.resume_page != null ? String(s.resume_page) : "—");
        set("scrapeStatDb", s.movies_in_db != null ? String(s.movies_in_db) : "—");
        if (s.movies_in_db != null) {
          const statCount = document.getElementById("statCount");
          if (statCount) statCount.textContent = String(s.movies_in_db);
        }

        const lastEl = document.getElementById("scrapeLastScanMeta");
        if (lastEl) {
          const parts = [];
          if (meta.saved_at) {
            parts.push(`Zapisano kolejkę: ${formatAdminTime(meta.saved_at)}`);
          }
          if (meta.candidates_found != null) {
            parts.push(`znaleziono ${meta.candidates_found}`);
          }
          if (meta.skipped != null) {
            parts.push(`pominięto ${meta.skipped} w bazie`);
          }
          if (meta.start_page != null && pages != null) {
            parts.push(`skan str. ${meta.start_page}–${meta.start_page + pages - 1}`);
          }
          if (s.last_scan?.saved > 0) {
            parts.push(`ostatnio pobrano +${s.last_scan.saved}`);
          }
          lastEl.textContent = parts.length ? parts.join(" · ") : "Ostatni skan: brak danych (kliknij Skanuj)";
        }

        const listEl = document.getElementById("scrapeQueueList");
        if (listEl) {
          const items = s.pending || [];
          if (!items.length) {
            listEl.hidden = true;
            listEl.innerHTML = "";
          } else {
            listEl.hidden = false;
            listEl.innerHTML = items
              .map(
                (m) =>
                  `<li>${escapeHtml(m.title || "?")}${m.year ? ` (${m.year})` : ""} <span class="admin-scrape-queue__id">#${m.id}</span></li>`
              )
              .join("");
          }
        }
      } catch {
        set("scrapeStatPending", "—");
        set("scrapeStatPages", "—");
        set("scrapeStatResume", "—");
        set("scrapeStatDb", "—");
      }
    }

    document.getElementById("scrapeScanBtn").addEventListener("click", async () => {
      const btn = document.getElementById("scrapeScanBtn");
      const log = document.getElementById("adminLog");
      const count = parseInt(document.getElementById("scrapeCount").value, 10) || 10;
      btn.disabled = true;
      document.getElementById("scrapeBtn").disabled = true;
      startScrapePollTimer(SCRAPE_POLL_ACTIVE_MS);
      log.textContent = `Skanowanie list YTS (szukam do ${count} nowych)…\n`;
      try {
        const result = await api("/admin/scrape/scan", {
          method: "POST",
          body: JSON.stringify({ count }),
        });
        log.textContent += (result.logs || []).join("\n") + "\n";
        if (result.resume_page) {
          log.textContent += `\nNastępne skanowanie od strony YTS: ${result.resume_page}`;
        }
        loadScrapeQueue();
        loadAutoScrape();
      } catch (err) {
        log.textContent += `\nError: ${err.message}`;
      } finally {
        btn.disabled = false;
        document.getElementById("scrapeBtn").disabled = false;
        if ((sessionStorage.getItem(ADMIN_TAB_KEY) || "movies") === "scraping") {
          startScrapePollTimer(SCRAPE_POLL_MS);
        }
      }
    });

    document.getElementById("scrapeForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = document.getElementById("scrapeBtn");
      const log = document.getElementById("adminLog");
      const count = parseInt(document.getElementById("scrapeCount").value, 10) || 10;
      btn.disabled = true;
      document.getElementById("scrapeScanBtn").disabled = true;
      startScrapePollTimer(SCRAPE_POLL_ACTIVE_MS);
      log.textContent = `Pobieranie z kolejki (max ${count})…\n`;
      try {
        const result = await api("/admin/scrape", {
          method: "POST",
          body: JSON.stringify({ count }),
        });
        log.textContent += (result.logs || []).join("\n") + "\n";
        log.textContent += `\n✓ Dodano ${result.saved} nowych filmów (w bazie: ${result.total_in_db})`;
        if (result.pending_count != null) {
          log.textContent += `\nW kolejce zostało: ${result.pending_count}`;
        }
        if (result.seo_urls && result.seo_urls.length) {
          log.textContent += `\nSEO: ${result.seo_urls.length} stron z meta (dodane do sitemap).`;
        }
        refreshAdminData();
        loadScrapeQueue();
        loadAutoScrape();
      } catch (err) {
        log.textContent += `\nError: ${err.message}`;
      } finally {
        btn.disabled = false;
        document.getElementById("scrapeScanBtn").disabled = false;
        if ((sessionStorage.getItem(ADMIN_TAB_KEY) || "movies") === "scraping") {
          startScrapePollTimer(SCRAPE_POLL_MS);
        }
      }
    });

    initAdminData();
    void fetchSiteBranding().then(applyAdminBranding).catch(() => {});
    if ((sessionStorage.getItem(ADMIN_TAB_KEY) || "movies") === "scraping") {
      startScrapePollTimer(SCRAPE_POLL_MS);
    }
    clearAdminRefreshTimer();
    adminRefreshTimer = setInterval(() => {
      loadStats();
    }, 30000);
  }

  async function render(app) {
    try {
      await api("/admin/me");
      renderDashboard(app);
      return;
    } catch (err) {
      if (isAuthError(err)) clearToken();
    }
    renderLogin(app, () => renderDashboard(app));
  }

  window.YtsAdmin = { render, cleanup: clearAllAdminTimers };
})();
