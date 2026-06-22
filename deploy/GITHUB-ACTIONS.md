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
| `DEPLOY_PORT` | `20203` (Virtuozzo; wewnętrznie sshd na 22) | opcjonalnie |
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
yts.cool  A  →  IP VPS (curl -4 ifconfig.me na nowym serwerze)
```

**Po migracji VPS** zaktualizuj rekord A — stary IP = Let's Encrypt nie wyda certyfikatu, deploy pada na „API not reachable through Caddy”.

Firewall: TCP **80**, **443**, **20203** (SSH Virtuozzo).

## SSH: Connection refused w Actions

1. Na VPS: `curl -4 ifconfig.me` → **DEPLOY_HOST** (u Ciebie: `103.155.93.120`, sam IP, bez enterów).
2. **Port SSH z internetu ≠ zawsze 22.** Sprawdź z laptopa (nie z VPS):
   ```bash
   nc -zv 103.155.93.120 22      # refused
   nc -zv 103.155.93.120 20203   # succeeded → DEPLOY_PORT=20203
   ```
   Virtuozzo często wystawia SSH tylko na niestandardowym porcie (np. **20203**).
3. Klucz deploy **musi** być w `authorized_keys` (pusty `grep deploy` = brak klucza → później Permission denied):
   ```bash
   mkdir -p /root/.ssh/deploy
   ssh-keygen -t ed25519 -f /root/.ssh/deploy/id_ed25519 -N ""
   cat /root/.ssh/deploy/id_ed25519.pub >> /root/.ssh/authorized_keys
   cat /root/.ssh/deploy/id_ed25519   # cały plik → GitHub Secret DEPLOY_SSH_KEY
   ```
4. Nie używaj domeny w `DEPLOY_HOST`, jeśli ma AAAA a IPv6 nie działa — wpisz **IPv4**.

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
