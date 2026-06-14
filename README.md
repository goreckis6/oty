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

## GitHub secrets

| Secret | Opis |
|--------|------|
| `DEPLOY_*`, `DOMAIN`, `ACME_EMAIL` | deploy VPS |
| `ADMIN_USER` / `ADMIN_PASSWORD` | logowanie admina |
| `JWT_SECRET` | token sesji (ustaw mocny!) |
| `DATA_SOURCE` | `sqlite` (domyślnie) lub `tmdb` |

## SQLite

- Plik: `backend/data/movies.db`
- Przy pierwszym uruchomieniu importuje `test_movies.json` jeśli baza pusta
- Volume Docker: `./backend/data:/app/data` — dane przetrwają redeploy
- **Deploy nie kasuje bazy** — `rsync` wyklucza `backend/data/*.db` (plik jest w `.gitignore`, ale zostaje na VPS)

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

## Deploy

```bash
git push origin main
```
