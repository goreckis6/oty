# GitHub Actions — deploy na VPS

Repo: [goreckis6/oty](https://github.com/goreckis6/oty/)  
Workflow: `.github/workflows/deploy.yml`  
Trigger: **push na `main`** lub **Actions → Deploy → Run workflow**

## Sekrety (Settings → Secrets → Actions)

| Secret | Produkcja (stary VPS) | Wymagany |
|--------|------------------------|----------|
| `DEPLOY_SSH_KEY` | klucz prywatny z `/root/.ssh/deploy/id_ed25519` | ✅ |
| `DEPLOY_USER` | `root` | ✅ |
| `DEPLOY_HOST` | `167.233.112.233` | ✅ |
| `DEPLOY_PORT` | `22` (domyślnie) | opcjonalnie |
| `DEPLOY_PATH` | `/opt/ytdown` | opcjonalnie |
| `DOMAIN` | `yts.cool` | opcjonalnie (HTTPS + health check) |
| `ACME_EMAIL` | `admin@example.com` | opcjonalnie (Let's Encrypt) |

**Virtuozzo (nowy VPS, jeśli wrócisz):** `DEPLOY_HOST=103.155.93.120`, `DEPLOY_PORT=20203`.

## Klucz SSH

Na VPS:

```bash
ssh-keygen -t ed25519 -f /root/.ssh/deploy/id_ed25519 -N ""
cat /root/.ssh/deploy/id_ed25519.pub >> /root/.ssh/authorized_keys
cat /root/.ssh/deploy/id_ed25519   # → GitHub Secret DEPLOY_SSH_KEY
```

## Co robi workflow

1. `rsync` plików na VPS (`--delete` — usuwa stare pliki aplikacji, **nie** kasuje: `backend/data/` z bazą/scrape, plików z panelu admina, `uploads/`, `downloads/`, `.well-known/`)
2. `deploy/scripts/deploy.sh` — Docker: API (SQLite) + Caddy
3. health check: `https://$DOMAIN/` (jeśli `DOMAIN` ustawione)

## DNS

```
yts.cool  A  →  167.233.112.233
```

Firewall: TCP **80**, **443**, **22** (SSH).

## SSH: Connection refused w Actions

1. `curl -4 ifconfig.me` na VPS = **DEPLOY_HOST** (sam IP, bez enterów).
2. Port SSH: stary VPS → **22**; Virtuozzo → często **20203** (`nc -zv IP 22`).
3. Klucz deploy w `authorized_keys` na tym samym serwerze co `DEPLOY_HOST`.

## Autostart po restarcie VPS

Każdy deploy:

1. Zapisuje `/opt/ytdown/.env` (sekrety + konfiguracja dla Docker Compose)
2. Instaluje `ytdown.service` (systemd)
3. Kontenery mają `restart: always` w `docker-compose.yml`

```bash
systemctl is-enabled docker ytdown   # oba: enabled
systemctl status ytdown
docker ps                            # site-api + site-caddy: Up
```

Ręczna instalacja:

```bash
APP_DIR=/opt/ytdown bash /opt/ytdown/deploy/scripts/install-boot-service.sh
```

## Ręczny deploy na VPS

```bash
cd /opt/ytdown
APP_DIR=/opt/ytdown DOMAIN=yts.cool bash deploy/scripts/deploy.sh
```
