# YTDown

Self-hosted YouTube video downloader (FastAPI + yt-dlp).

## Co musi być na serwerze

| Wymaganie | Po co |
|-----------|--------|
| **Linux** (Ubuntu/Debian) | hosting |
| **Python 3.10+** | backend |
| **python3-venv** | wirtualne środowisko |
| **ffmpeg** | scalanie wideo+audio (720p, 1080p, 4K) |
| **git**, **rsync**, **curl** | deploy i healthcheck |
| **systemd** | autostart po restarcie |

Opcjonalnie:
- **nginx** — reverse proxy, HTTPS, domena
- cookies YouTube (`YTDOWN_COOKIES_BROWSER`) — gdy YouTube blokuje pobieranie

---

## Deploy: GitHub Actions → serwer

### 1. Jednorazowa konfiguracja serwera

```bash
# Na serwerze (jako root)
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg curl rsync git

# Skopiuj pliki projektu do /opt/ytdown (pierwszy raz)
sudo mkdir -p /opt/ytdown
sudo rsync -av ./ /opt/ytdown/   # z lokalnej maszyny

# Utwórz użytkownika i systemd
cd /opt/ytdown
sudo bash deploy/install-server.sh

# Konfiguracja
sudo nano /etc/ytdown/env
# YTDOWN_HOST=0.0.0.0
# YTDOWN_PORT=8082

# Pierwszy deploy
sudo APP_DIR=/opt/ytdown bash deploy/remote-deploy.sh
```

### 2. Sekrety w GitHub (Settings → Secrets)

| Secret | Przykład | Opis |
|--------|----------|------|
| `DEPLOY_HOST` | `192.168.1.50` | IP lub domena serwera |
| `DEPLOY_USER` | `deploy` | użytkownik SSH |
| `DEPLOY_SSH_KEY` | `-----BEGIN OPENSSH...` | klucz prywatny SSH |
| `DEPLOY_PORT` | `22` | opcjonalnie |
| `DEPLOY_PATH` | `/opt/ytdown` | opcjonalnie |

### 3. Uprawnienia deploy usera

Użytkownik SSH musi móc zapisywać do `/opt/ytdown` i restartować usługę:

```bash
# /etc/sudoers.d/ytdown-deploy
deploy ALL=(ALL) NOPASSWD: /opt/ytdown/deploy/remote-deploy.sh
```

Nadaj własność katalogu:

```bash
sudo chown -R deploy:ytdown /opt/ytdown
sudo chmod -R g+w /opt/ytdown
sudo usermod -aG ytdown deploy
```

### 4. Push na `main`

Każdy push na branch `main` uruchamia `.github/workflows/deploy.yml`:

1. `rsync` plików na serwer
2. `pip install` w `.venv`
3. `systemctl restart ytdown`
4. healthcheck `/api/health`

Ręczny deploy: **Actions → Deploy → Run workflow**.

---

## Kubernetes

Aplikacja jest opakowana w obraz Docker + manifesty K8s.

```bash
# zbuduj obraz
docker build -t ghcr.io/TWOJ_USER/ytdown:latest .

# edytuj k8s/kustomization.yaml (nazwa obrazu)
kubectl apply -k k8s/

# test lokalny
kubectl -n ytdown port-forward svc/ytdown 8080:80
```

Szczegóły: **[k8s/README.md](k8s/README.md)**

| Plik | Opis |
|------|------|
| `Dockerfile` | obraz z Python + ffmpeg |
| `k8s/deployment.yaml` | pod aplikacji |
| `k8s/service.yaml` | ClusterIP :80 → :8080 |
| `k8s/ingress.yaml` | opcjonalny dostęp przez domenę |
| `.github/workflows/docker.yml` | CI → GHCR |

> **Uwaga:** na razie `replicas: 1` — status pobierania jest w pamięci, więc wiele replik nie zadziała bez Redis/bazy.

---

## VPS — najszybszy deploy (5 min)

### 1. Wyślij pliki

```bash
rsync -avz --exclude '.git' --exclude 'backend/.venv' --exclude 'bin' --exclude 'downloads' \
  ./ root@TWOJE_IP:/opt/ytdown/
```

### 2. Uruchom

```bash
ssh root@TWOJE_IP 'cd /opt/ytdown && bash deploy/scripts/deploy-single.sh'
```

### 3. Firewall

```bash
ufw allow 8082/tcp && ufw allow OpenSSH && ufw enable
```

Otwórz: **http://TWOJE_IP:8082**

### Przydatne komendy

```bash
docker compose logs -f
docker compose up -d --build    # aktualizacja
```

### GitHub Actions (jeden VPS)

Sekrety: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` → **[deploy/GITHUB-ACTIONS.md](deploy/GITHUB-ACTIONS.md)**

Po Terraform: **[deploy/POST-TERRAFORM.md](deploy/POST-TERRAFORM.md)**

### Opcjonalnie: LB + wiele maszyn

**[deploy/load-balancer/README.md](deploy/load-balancer/README.md)**

---

## Lokalny development

```bash
cp deploy/env.example .env   # opcjonalnie
./start.sh
```

Otwórz `http://127.0.0.1:8082`.

### YouTube bot detection

```bash
export YTDOWN_COOKIES_BROWSER=chrome
./start.sh
```

---

## Struktura projektu

```
ytdown/
├── Dockerfile
├── .github/workflows/
│   ├── deploy.yml           # SSH deploy
│   └── docker.yml           # build → GHCR
├── backend/main.py
├── deploy/                  # systemd / bare metal
├── k8s/                     # Kubernetes
├── frontend/
├── scripts/run.sh
└── start.sh
```

---

## API

| Endpoint | Opis |
|----------|------|
| `POST /api/analyze` | metadane + formaty |
| `POST /api/download/start` | rozpocznij pobieranie |
| `GET /api/download/status/{id}` | postęp |
| `GET /api/download/file/{id}` | pobierz plik |
| `GET /api/health` | status serwera |

---

## Disclaimer

Do użytku osobistego, niekomercyjnego. Niezależny projekt — brak powiązania z YouTube.
