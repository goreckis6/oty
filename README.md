# YTS — yts.cool

Frontend + własny backend API. **Bez yts.bz.**

## Skąd biorą się dane

| Co | Źródło |
|----|--------|
| Filmy, opisy, plakaty, oceny | [TMDB API](https://www.themoviedb.org/settings/api) |
| Torrenty / magnety | Wyszukiwarka torrentów (domyślnie apibay.org) lub Twój Torznab (Jackett/Prowlarr) |

```
yts.cool/           → frontend
yts.cool/api/v1/    → backend (FastAPI)
                      ├─ TMDB — metadane filmów
                      └─ apibay / Torznab — linki torrent
```

## GitHub secrets (wymagane)

| Secret | Skąd wziąć |
|--------|------------|
| `DEPLOY_SSH_KEY`, `DEPLOY_USER`, `DEPLOY_HOST` | VPS |
| `DOMAIN` | `yts.cool` |
| `ACME_EMAIL` | twój email (HTTPS) |
| **`TMDB_API_KEY`** | [themoviedb.org](https://www.themoviedb.org/settings/api) — darmowy klucz API |

## Opcjonalne

| Secret | Domyślnie | Opis |
|--------|-----------|------|
| `TORRENT_SOURCE` | `apibay` | `apibay`, `torznab` lub `none` |
| `TORZNAB_URL` | — | URL Jackett/Prowlarr Torznab |
| `TORZNAB_API_KEY` | — | klucz Torznab |
| `SITE_NAME` | `YTS` | nazwa strony |

## Deploy

```bash
git push origin main
```

Ręcznie na VPS:

```bash
cd /opt/ytdown
TMDB_API_KEY=twój_klucz DOMAIN=yts.cool ACME_EMAIL=you@mail.com bash deploy/scripts/deploy.sh
```

## Test API

```bash
curl https://yts.cool/api/v1/health
curl "https://yts.cool/api/v1/list_movies.json?limit=2"
curl "https://yts.cool/api/v1/movie_details.json?movie_id=27205"
```

## Lokalnie

```bash
cd backend
TMDB_API_KEY=xxx TORRENT_SOURCE=apibay uvicorn main:app --reload --port 8080
```
