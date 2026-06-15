(function () {
  const TOKEN_KEY = "yts_admin_token";
  let adminRefreshTimer = null;

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

  function renderLogin(app, onSuccess) {
    app.innerHTML = `
      <div class="admin-wrap">
        <div class="admin-card">
          <h1>Admin Panel</h1>
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
  }

  function renderDashboard(app) {
    let moviesPage = 1;
    let moviesLimit = 50;
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

          <nav class="admin-tabs" id="adminTabs" role="tablist" aria-label="Sekcje panelu">
            <button type="button" class="admin-tabs__btn admin-tabs__btn--active" data-tab="movies" role="tab" aria-selected="true">Filmy</button>
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

          <section class="admin-tab admin-section" data-tab="scraping" id="adminTabScraping" role="tabpanel" hidden>
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

            <h2 class="admin-tab__subtitle">Auto scraping</h2>
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
            <p class="admin-hint">Dodaj pliki weryfikacyjne (Google, Bing) w katalogu głównym witryny. Będą dostępne pod adresem <code>https://twoja-domena/nazwa-pliku.html</code>. Chronione: <code>index.html</code>, katalogi <code>js/</code> i <code>css/</code>.</p>
            <div class="admin-files-toolbar">
              <button type="button" class="btn-admin-outline" id="adminFilesRefresh">Odśwież</button>
            </div>
            <div class="admin-files-create">
              <h3>Nowy plik</h3>
              <form id="adminFileCreateForm" class="admin-file-form">
                <label>
                  Nazwa pliku
                  <input type="text" id="adminFileName" placeholder="google123abc.html" pattern="[A-Za-z0-9._-]+" required />
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
                  <input type="file" id="adminUploadFile" accept=".html,.htm,.txt,.xml,.json" required />
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
      clearAdminRefreshTimer();
      try {
        await api("/admin/logout", { method: "POST" });
      } catch {
        /* cookie may already be gone */
      }
      clearToken();
      window.YtsAdmin.render(app);
    });

    const ADMIN_TAB_KEY = "yts_admin_tab";
    const validTabs = new Set(["movies", "scraping", "branding", "files"]);

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
      if (name === "scraping") loadAutoScrape();
    }

    document.getElementById("adminTabs").addEventListener("click", (e) => {
      const btn = e.target.closest(".admin-tabs__btn");
      if (!btn) return;
      switchTab(btn.dataset.tab);
    });

    const initialTab = sessionStorage.getItem(ADMIN_TAB_KEY) || "movies";
    switchTab(validTabs.has(initialTab) ? initialTab : "movies");

    document.getElementById("adminMoviesLimit").value = String(moviesLimit);
    document.getElementById("adminMoviesLimit").addEventListener("change", (e) => {
      moviesLimit = parseInt(e.target.value, 10) || 100;
      moviesPage = 1;
      loadMovies();
    });

    function updateBrandingPreview(b) {
      const name = b.siteName || "YTS";
      const tag = b.siteTagline || "HD movies at the smallest file size";
      const logoText = document.getElementById("adminPreviewLogoText");
      const logoImg = document.getElementById("adminPreviewLogoImg");
      const tagEl = document.getElementById("adminPreviewTagline");
      const removeBtn = document.getElementById("adminLogoRemove");

      if (tagEl) tagEl.textContent = tag;
      if (b.logoType === "image" && b.logoUrl) {
        if (logoImg) {
          logoImg.src = b.logoUrl;
          logoImg.alt = name;
          logoImg.hidden = false;
        }
        if (logoText) logoText.hidden = true;
        if (removeBtn) removeBtn.hidden = false;
      } else {
        if (logoText) {
          logoText.textContent = name;
          logoText.hidden = false;
        }
        if (logoImg) logoImg.hidden = true;
        if (removeBtn) removeBtn.hidden = true;
      }
    }

    async function loadBranding() {
      try {
        const b = await api("/admin/branding");
        document.getElementById("adminSiteName").value = b.siteName || "";
        document.getElementById("adminSiteTagline").value = b.siteTagline || "";
        updateBrandingPreview(b);
        syncSiteBranding(b);
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
        syncSiteBranding(b);
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
        syncSiteBranding(b);
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
        syncSiteBranding(b);
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

    function formatAutoStatus(s) {
      const lines = [];
      lines.push(s.enabled ? "Status: włączone" : "Status: wyłączone");
      if (s.scrape_resume_page) {
        lines.push(`Kolejna strona YTS: ${s.scrape_resume_page}`);
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
          let msg = `Ostatni wynik: +${r.saved || 0}`;
          if (r.skipped) msg += `, pominięto ${r.skipped}`;
          if (r.pages_scanned) msg += ` (${r.pages_scanned} str.)`;
          if (r.start_page) msg += `, od str. ${r.start_page}`;
          if (r.resume_page) msg += ` → nast. ${r.resume_page}`;
          msg += ` (w bazie: ${r.total_in_db || "?"})`;
          lines.push(msg);
        }
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

    async function applyStats(s) {
      document.getElementById("statCount").textContent = s.movies_count;
      document.getElementById("statLast").textContent = s.last_scrape || "never";
      document.getElementById("statBatch").textContent = s.last_scrape_count || "—";
      document.getElementById("statNew").textContent = s.new_count ?? "—";
    }

    function renderMoviesTable(data) {
      const tbody = document.getElementById("adminMoviesBody");
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
    }

    async function loadBootstrap() {
      const tbody = document.getElementById("adminMoviesBody");
      try {
        const data = await api(`/admin/bootstrap?page=${moviesPage}&limit=${moviesLimit}`);
        applyStats(data);
        renderMoviesTable(data);
      } catch (err) {
        if (isAuthError(err)) {
          clearToken();
          window.YtsAdmin.render(app);
          return;
        }
        tbody.innerHTML = `<tr><td colspan="7" class="admin-movies-empty">Błąd: ${escapeHtml(err.message)}</td></tr>`;
      }
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
        const data = await api(`/admin/movies?page=${moviesPage}&limit=${moviesLimit}`);
        renderMoviesTable(data);
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
        loadBootstrap();
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
        loadBootstrap();
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
        if (result.resume_page) {
          log.textContent += `\nNastępne skanowanie od strony YTS: ${result.resume_page}`;
        }
        loadBootstrap();
      } catch (err) {
        log.textContent += `\nError: ${err.message}`;
      } finally {
        btn.disabled = false;
      }
    });

    loadBootstrap();
    clearAdminRefreshTimer();
    adminRefreshTimer = setInterval(() => {
      loadStats();
      if ((sessionStorage.getItem(ADMIN_TAB_KEY) || "movies") === "scraping") loadAutoScrape();
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

  window.YtsAdmin = { render, cleanup: clearAdminRefreshTimer };
})();
