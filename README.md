# YTS — yts.cool

Frontend + backend API na jednym VPS. Deploy: GitHub Actions → rsync → Docker.

## Architektura

```
yts.cool/              → frontend (HTML/CSS/JS)
yts.cool/api/v1/       → backend (FastAPI, Docker port 8080)
                         ↳ proxy do YTS upstream (domyślnie yts.bz/api/v2)
```

## GitHub secrets

| Secret | Przykład | Wymagany |
|--------|----------|----------|
| `DEPLOY_SSH_KEY` | klucz SSH | ✅ |
| `DEPLOY_USER` | `root` | ✅ |
| `DEPLOY_HOST` | `167.233.112.233` | ✅ |
| `DOMAIN` | `yts.cool` | ✅ (HTTPS) |
| `ACME_EMAIL` | `admin@example.com` | ✅ (Let's Encrypt) |
| `YTS_UPSTREAM` | `https://yts.bz/api/v2` | opcjonalnie |
| `SITE_NAME` | `YTS` | opcjonalnie |

**Nie potrzebujesz `YTS_API_URL`** — API jest na `https://yts.cool/api/v1` automatycznie.

## API endpoints

| URL | Opis |
|-----|------|
| `GET /api/v1/list_movies.json` | Lista filmów |
| `GET /api/v1/movie_details.json?movie_id=ID` | Szczegóły filmu |
| `GET /api/v1/list_upcoming.json` | Nadchodzące |
| `GET /api/v1/movie_suggestions.json?movie_id=ID` | Podobne filmy |
| `GET /api/v1/health` | Health check |

## Lokalnie

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8080

# Frontend (osobny terminal)
cd public
python3 -m http.server 3000
# Ustaw w config.js: apiBase: "http://127.0.0.1:8080/api/v1"
```

## Deploy

Push na `main` uruchamia GitHub Actions. Ręcznie na VPS:

```bash
cd /opt/ytdown
APP_DIR=/opt/ytdown DOMAIN=yts.cool ACME_EMAIL=you@mail.com bash deploy/scripts/deploy.sh
```

## Struktura

```
backend/           FastAPI proxy → YTS upstream
public/            Frontend SPA
docker-compose.yml API + Caddy
deploy/scripts/    deploy.sh
```
