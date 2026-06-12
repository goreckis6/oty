# GitHub Actions — jeden VPS (bez LB)

Repo: [goreckis6/oty](https://github.com/goreckis6/oty/)  
Workflow: `.github/workflows/deploy.yml`  
Trigger: **push na `main`** lub **Actions → Deploy → Run workflow**

## Sekrety (Settings → Secrets → Actions)

| Secret | Przykład | Wymagany |
|--------|----------|----------|
| `DEPLOY_SSH_KEY` | `-----BEGIN OPENSSH...` | ✅ |
| `DEPLOY_USER` | `root` | ✅ |
| `DEPLOY_HOST` | `167.233.112.233` | ✅ IP Twojego VPS |
| `DEPLOY_PORT` | `22` | opcjonalnie |
| `DEPLOY_PATH` | `/opt/ytdown` | opcjonalnie |
| `DOMAIN` | `yts.cool` | opcjonalnie (domyślnie yts.cool) |
| `ACME_EMAIL` | `admin@example.com` | opcjonalnie (Let's Encrypt) |
| `DEPLOY_MODE` | `native` | `native` (jak start.sh) lub `docker` |

> Stare sekrety `LB_HOST` i `WORKERS` **nie są już używane**.

## Klucz SSH

Na VPS:

```bash
ssh-keygen -t ed25519 -f /root/.ssh/ytdown-deploy/id_ed25519 -N ""
cat /root/.ssh/ytdown-deploy/id_ed25519.pub >> /root/.ssh/authorized_keys

# klucz prywatny → GitHub Secret DEPLOY_SSH_KEY
cat /root/.ssh/ytdown-deploy/id_ed25519
```

Lub skrypt: `deploy/scripts/setup-deploy-ssh.sh` (bez `LB_HOST` / `WORKERS`).

## Co robi workflow

1. `rsync` kodu na VPS
2. `deploy-single.sh` — domyślnie **native** (Python + systemd + Caddy na hoście); opcjonalnie `DEPLOY_MODE=docker`
3. health check: `https://yts.cool/api/health`

## DNS (przed pierwszym deployem)

Ustaw rekord **A** w DNS domeny:

```
yts.cool  →  IP Twojego VPS (np. 167.233.112.233)
```

W panelu Hetzner Cloud Firewall dodaj reguły **TCP 80** i **TCP 443** (oraz SSH 22).

## Pierwszy raz na VPS

Firewall konfiguruje się przy deployu (`ufw allow 80, 443`). Docker instaluje się automatycznie.

## Aplikacja po deployu

**https://yts.cool**

## Rozbudowa o LB (później)

Zobacz `deploy/load-balancer/README.md` i `docker-compose.worker.yml`.
