# YTS — yts.cool

Frontend + SQLite API + panel admina.

## Architektura

```
yts.cool/              → frontend
yts.cool/api/v1/       → FastAPI + SQLite
yts.cool/twojastara    → panel admina (login + scraping)
backend/data/movies.db → baza filmów (volume Docker)
```

## Panel admina

URL: **`https://yts.cool/twojastara`**

Domyślne dane logowania (zmień w GitHub Secrets!):

| Secret | Domyślnie |
|--------|-----------|
| `ADMIN_USER` | `admin` |
| `ADMIN_PASSWORD` | `admin` |
| `JWT_SECRET` | losowy długi string |

W panelu:
- statystyki bazy (ile filmów)
- **Start scraping** — pobiera N filmów z yts.bz do SQLite
- **Pliki witryny** — tworzenie/upload plików weryfikacyjnych (Google, Bing) w katalogu głównym
- **Wygląd witryny** — zmiana nazwy/logo i tagline w nagłówku

## GitHub secrets

| Secret | Opis |
|--------|------|
| `DEPLOY_*`, `DOMAIN`, `ACME_EMAIL` | deploy VPS |
| `ADMIN_USER` / `ADMIN_PASSWORD` | logowanie admina |
| `JWT_SECRET` | token sesji (ustaw mocny!) |
| `DATA_SOURCE` | `sqlite` (domyślnie) lub `tmdb` |

## SQLite

- Plik: `backend/data/movies.db`
- Przy pierwszym uruchomieniu baza startuje pusta — filmy dodajesz przez scraping w panelu admina
- Volume Docker: `./backend/data:/app/data` — dane przetrwają redeploy
- **Deploy NIGDY nie kasuje bazy** — `rsync` wyklucza cały `backend/data/` (zostaje tylko `test_movies.json` z repo); `deploy.sh` weryfikuje `movies.db` przed i po deployu
- **Deploy nie kasuje plików z panelu** — weryfikacja Google/Bing (`public/*.html` poza `index.html`), `public/uploads/` (logo), `public/downloads/`, `public/.well-known/`
- **Google Analytics** — tag `G-E57KES06CY` w `public/index.html`

## CLI scraping

```bash
cd backend
python3 scrape_yts.py -n 20
```

## API admina

| Endpoint | Auth | Opis |
|----------|------|------|
| `POST /api/v1/admin/login` | — | `{username, password}` → token |
| `GET /api/v1/admin/stats` | Bearer | statystyki |
| `POST /api/v1/admin/scrape` | Bearer | `{count: 10}` |
| `GET /api/v1/admin/auto-scrape` | Bearer | ustawienia auto-scrapingu |
| `POST /api/v1/admin/auto-scrape` | Bearer | `{enabled, interval_minutes, count}` — min. 5 min |
| `GET /api/v1/admin/movies?page=1&limit=100` | Bearer | lista filmów (100/200/300/500) |
| `GET /api/v1/admin/files` | Bearer | pliki w katalogu głównym witryny |
| `PUT /api/v1/admin/files` | Bearer | `{path, content}` — utwórz/edytuj plik tekstowy |
| `POST /api/v1/admin/files/upload` | Bearer | multipart upload pliku weryfikacyjnego |
| `DELETE /api/v1/admin/files?path=...` | Bearer | usuń plik (oprócz chronionych) |
| `GET /api/v1/site/branding` | — | nazwa, tagline i logo witryny |
| `GET/POST /api/v1/admin/branding` | Bearer | edycja nazwy i tagline |
| `POST /api/v1/admin/branding/logo` | Bearer | upload logo (PNG/JPG/WEBP/SVG) |
| `DELETE /api/v1/admin/branding/logo` | Bearer | usuń logo, wróć do tekstu |

## Deploy

```bash
git push origin main
```
