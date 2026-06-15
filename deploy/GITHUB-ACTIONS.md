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

Firewall: TCP **80**, **443**, **22**.

## Migracja na nowy serwer

Zobacz **[MIGRATE-SERVER.md](MIGRATE-SERVER.md)** — bootstrap, kopia `movies.db`, zmiana `DEPLOY_HOST`, DNS, wyłączenie starego VPS.

Skrypty:

| Skrypt | Gdzie uruchomić |
|--------|-----------------|
| `deploy/scripts/bootstrap-server.sh` | nowy VPS |
| `deploy/scripts/migrate-data.sh` | laptop (SSH do obu serwerów) |
| `deploy/scripts/shutdown-old-server.sh` | stary VPS (po przełączeniu DNS) |

## Ręczny deploy na VPS

```bash
cd /opt/ytdown
APP_DIR=/opt/ytdown DOMAIN=twoja-domena bash deploy/scripts/deploy.sh
```
