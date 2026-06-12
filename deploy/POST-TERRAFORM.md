# Deploy na jeden VPS (po Terraform)

Masz jeden serwer z Terraform — **bez load balancera**.

## IP serwera

Z output Terraform weź IP workera (lub jedynego VPS):

```
DEPLOY_HOST = 167.233.112.233
```

## Ręczny deploy

```bash
rsync -avz --exclude '.git' --exclude 'downloads' ./ root@IP:/opt/ytdown/
ssh root@IP 'cd /opt/ytdown && DOMAIN=yts.cool bash deploy/scripts/deploy-single.sh'
```

Ustaw DNS: **yts.cool** → IP VPS. Otwórz: **https://yts.cool**

## GitHub Actions

Sekrety w [goreckis6/oty](https://github.com/goreckis6/oty/):

| Secret | Wartość |
|--------|---------|
| `DEPLOY_HOST` | IP VPS |
| `DEPLOY_USER` | `root` |
| `DEPLOY_SSH_KEY` | klucz prywatny |

Szczegóły: **[GITHUB-ACTIONS.md](GITHUB-ACTIONS.md)**

## DNS i firewall

```
yts.cool  A  →  IP VPS
```

```bash
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow OpenSSH
ufw enable
```

Caddy (w docker-compose) wystawia HTTPS automatycznie.
