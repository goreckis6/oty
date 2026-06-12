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
ssh root@IP 'cd /opt/ytdown && PUBLIC_PORT=3000 bash deploy/scripts/deploy-single.sh'
```

Otwórz: **http://167.233.112.233:3000**

## GitHub Actions

Sekrety w [goreckis6/oty](https://github.com/goreckis6/oty/):

| Secret | Wartość |
|--------|---------|
| `DEPLOY_HOST` | IP VPS |
| `DEPLOY_USER` | `root` |
| `DEPLOY_SSH_KEY` | klucz prywatny |

Szczegóły: **[GITHUB-ACTIONS.md](GITHUB-ACTIONS.md)**

## Firewall

```bash
ufw allow 3000/tcp
ufw allow OpenSSH
ufw enable
```
