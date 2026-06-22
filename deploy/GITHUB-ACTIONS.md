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
twoja-domena  A  →  IP VPS
```

Firewall: TCP **80**, **443**, **22** (port 22 must be open to GitHub Actions, not only your home IP).

## SSH: Connection refused w Actions

1. Na VPS: `curl -4 ifconfig.me` — to musi być **DEPLOY_HOST** w GitHub (sam IP, bez spacji/entera).
2. Panel hostingu (Virtuozzo): otwórz **TCP 22** dla wszystkich (0.0.0.0/0).
3. Nie używaj domeny w `DEPLOY_HOST`, jeśli ma rekord AAAA a IPv6 nie działa — wpisz **IPv4**.
4. Test z zewnątrz: port checker na IP + port 22.

## Autostart po restarcie VPS

Każdy deploy instaluje `ytdown.service` (systemd) + `restart: always` w Dockerze.

```bash
systemctl is-enabled docker ytdown   # oba: enabled
docker ps                            # site-api + site-caddy: Up
```

## Ręczny deploy na VPS

```bash
cd /opt/ytdown
APP_DIR=/opt/ytdown DOMAIN=twoja-domena bash deploy/scripts/deploy.sh
```
