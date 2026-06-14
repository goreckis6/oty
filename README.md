# YTS Frontend — VPS Deploy

Static YTS-style frontend that connects to **your existing YTS API v2 backend**. Deploys via GitHub Actions → VPS (Caddy).

## Features

- Home page (latest + upcoming movies)
- Browse with filters (quality, genre, rating, sort)
- Search
- Movie detail page (poster, info, torrent/magnet links)
- Mobile responsive, YTS green theme

## API compatibility

Expects standard [YTS API v2](https://github.com/BrokenEmpire/YTS/blob/master/API.md) endpoints:

| Endpoint | Used for |
|----------|----------|
| `GET /api/v2/list_movies.json` | Browse, search, filters |
| `GET /api/v2/movie_details.json` | Movie page |
| `GET /api/v2/list_upcoming.json` | Upcoming section |
| `GET /api/v2/movie_suggestions.json` | Similar movies |

## GitHub secrets

| Secret | Example | Required |
|--------|---------|----------|
| `DEPLOY_SSH_KEY` | private SSH key | ✅ |
| `DEPLOY_USER` | `root` | ✅ |
| `DEPLOY_HOST` | `167.233.112.233` | ✅ |
| `DOMAIN` | `yts.cool` | recommended |
| `ACME_EMAIL` | `admin@example.com` | for HTTPS |
| `YTS_API_BACKEND` | `127.0.0.1:8080` | if API runs on same VPS |
| `YTS_API_URL` | `https://yts.bz/api/v2` | if API is external (skip proxy) |
| `SITE_NAME` | `YTS` | optional |
| `SITE_TAGLINE` | `HD at smallest size` | optional |

### API connection — pick one

**Option 1 — API on same VPS (recommended)**

Caddy proxies `/api/v2/*` to your backend:

```
YTS_API_BACKEND=127.0.0.1:8080
```

Frontend calls `/api/v2` (same origin, no CORS).

**Option 2 — External API URL**

Point frontend directly at your API (API must allow CORS):

```
YTS_API_URL=https://your-api.example.com/api/v2
```

Do not set `YTS_API_BACKEND` in this case.

## Local preview

Serve `public/` and set API in `public/js/config.js`:

```bash
cd public
python3 -m http.server 3000
```

Open http://localhost:3000 — set `apiBase` to your API URL.

## VPS manual deploy

```bash
cd /opt/ytdown
APP_DIR=/opt/ytdown \
DOMAIN=yts.cool \
YTS_API_BACKEND=127.0.0.1:8080 \
SITE_NAME=YTS \
bash deploy/scripts/deploy.sh
```

## Project layout

```
public/
  index.html          # SPA shell
  css/style.css       # YTS theme
  js/config.js        # API URL (generated on deploy)
  js/api.js           # YTS API client
  js/app.js           # Pages + routing
deploy/scripts/deploy.sh
docker-compose.yml    # Caddy
.github/workflows/deploy.yml
```

## Push to deploy

```bash
git add .
git commit -m "Add YTS frontend"
git push origin main
```

GitHub Actions rsyncs to VPS and runs `deploy.sh`.
