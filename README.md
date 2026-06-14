# VPS deploy skeleton

Minimal repo for **GitHub Actions → VPS** deploy. Application code goes here when you build the new site.

## What's included

| Path | Purpose |
|------|---------|
| `.github/workflows/deploy.yml` | rsync + SSH deploy on push to `main` |
| `deploy/scripts/deploy.sh` | runs on VPS after each deploy |
| `docker-compose.yml` | Caddy + static `public/` placeholder |
| `deploy/GITHUB-ACTIONS.md` | GitHub secrets setup |

## GitHub secrets

| Secret | Example |
|--------|---------|
| `DEPLOY_HOST` | `167.233.112.233` |
| `DEPLOY_USER` | `root` |
| `DEPLOY_SSH_KEY` | private SSH key |
| `DEPLOY_PORT` | `22` (optional) |
| `DEPLOY_PATH` | `/opt/ytdown` (optional) |
| `DOMAIN` | your domain |
| `ACME_EMAIL` | email for HTTPS (optional) |

## Local

Edit `public/index.html`, push to `main` — GitHub Actions deploys to VPS.

## VPS manual deploy

```bash
cd /opt/ytdown
git pull   # or wait for Actions rsync
APP_DIR=/opt/ytdown DOMAIN=yts.cool bash deploy/scripts/deploy.sh
```

Legacy YTDown Docker containers are stopped automatically on deploy.
