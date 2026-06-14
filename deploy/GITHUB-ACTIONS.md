# GitHub Actions — deploy na VPS

Repo: [goreckis6/oty](https://github.com/goreckis6/oty/)  
Workflow: `.github/workflows/deploy.yml`  
Trigger: **push na `main`** lub **Actions → Deploy → Run workflow**

## Sekrety (Settings → Secrets → Actions)

| Secret | Przykład | Wymagany |
|--------|----------|----------|
| `DEPLOY_SSH_KEY` | `-----BEGIN OPENSSH...` | ✅ |
| `DEPLOY_USER` | `root` | ✅ |
| `DEPLOY_HOST` | `167.233.112.233` | ✅ |
| `DEPLOY_PORT` | `22` | opcjonalnie |
| `DEPLOY_PATH` | `/opt/ytdown` | opcjonalnie |
| `DOMAIN` | `yts.cool` | opcjonalnie (HTTPS + health check) |
| `ACME_EMAIL` | `admin@example.com` | opcjonalnie (Let's Encrypt) |
| `YTS_API_BACKEND` | `127.0.0.1:8080` | API na tym samym VPS (proxy przez Caddy) |
| `YTS_API_URL` | `https://twoja-api/api/v2` | zewnętrzne API (zamiast proxy) |
| `SITE_NAME` | `YTS` | opcjonalnie |
| `SITE_TAGLINE` | `HD at smallest size` | opcjonalnie |

## Klucz SSH

Na VPS:

```bash
ssh-keygen -t ed25519 -f /root/.ssh/deploy/id_ed25519 -N ""
cat /root/.ssh/deploy/id_ed25519.pub >> /root/.ssh/authorized_keys
cat /root/.ssh/deploy/id_ed25519   # → GitHub Secret DEPLOY_SSH_KEY
```

## Co robi workflow

1. `rsync` plików na VPS (`--delete` — usuwa stare pliki aplikacji)
2. `deploy/scripts/deploy.sh` — Caddy + frontend YTS, opcjonalny proxy `/api/v2` → backend
3. health check: `https://$DOMAIN/` (jeśli `DOMAIN` ustawione)

## DNS

```
twoja-domena  A  →  IP VPS
```

Firewall: TCP **80**, **443**, **22**.

## Ręczny deploy na VPS

```bash
cd /opt/ytdown
APP_DIR=/opt/ytdown DOMAIN=twoja-domena bash deploy/scripts/deploy.sh
```
