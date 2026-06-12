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
| `PUBLIC_PORT` | `8082` | opcjonalnie (domyślnie 8082) |

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
2. `docker compose up -d --build`
3. health check: `http://DEPLOY_HOST:8082/api/health`

## Pierwszy raz na VPS

```bash
ufw allow 8082/tcp
ufw allow OpenSSH
ufw enable
```

Docker instaluje się automatycznie przy pierwszym deployu.

## Aplikacja po deployu

**http://167.233.112.233:8082**

## Rozbudowa o LB (później)

Zobacz `deploy/load-balancer/README.md` i `docker-compose.worker.yml`.
