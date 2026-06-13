# Backend na domowym PC + domena na VPS

YouTube działa lokalnie, bo ruch wychodzi z **domowego IP**. VPS ma IP datacenter — stąd blokady.

Rozwiązanie:

```text
Użytkownik → yts.cool (VPS, Caddy, HTTPS)
                ↓ tunel / Tailscale
           Twój PC (backend + yt-dlp, domowe IP)
                ↓
            YouTube
```

VPS **nie** pobiera z YouTube — tylko przekazuje ruch do Twojego komputera.

---

## 1. Backend u siebie (Linux)

```bash
cd ~/ytdown
sudo apt install -y python3 python3-venv ffmpeg nodejs   # raz
chmod +x scripts/start-home.sh
./scripts/start-home.sh
```

Sprawdź w LAN:

```bash
curl http://127.0.0.1:8080/api/health
```

Opcjonalnie w `.env`:

```bash
YTDOWN_COOKIES_BROWSER=chrome
WORKER_ID=home
```

---

## 2. Połączenie VPS ↔ dom (wybierz jedno)

### A. Tailscale (zalecane)

1. [tailscale.com](https://tailscale.com) — zainstaluj na PC i VPS, ten sam account.
2. Na PC: `tailscale ip -4` → np. `100.64.0.5`
3. Na VPS:

```bash
cd /opt/ytdown
HOME_BACKEND_URL=http://100.64.0.5:8080 DOMAIN=yts.cool bash deploy/scripts/setup-vps-home-proxy.sh
docker compose down          # stary stack z yt-dlp na VPS
docker compose -f docker-compose.vps-proxy.yml up -d
```

4. PC musi być włączony, `./scripts/start-home.sh` działa.

### B. SSH reverse tunnel (szybki test)

Na **domowym PC**:

```bash
./scripts/connect-home-to-vps.sh
```

Skrypt próbuje porty `19080`, `19081`, `19082` (domyślnie `18080` bywa zajęty).

Jeśli zobaczysz `remote port forwarding failed` — na VPS:

```bash
ss -tlnp | grep -E '18080|19080'
fuser -k 18080/tcp 2>/dev/null
fuser -k 19080/tcp 2>/dev/null
```

Albo wymuś inny port u siebie:

```bash
REMOTE_PORT=19100 ./scripts/connect-home-to-vps.sh
```

Na **VPS** (użyj **tego samego portu**, który tunel przyjął — np. `19080`):

```bash
HOME_BACKEND_URL=http://127.0.0.1:28080 DOMAIN=yts.cool bash deploy/scripts/setup-vps-home-proxy.sh
docker compose down
docker compose -f docker-compose.vps-proxy.yml up -d
curl -s http://127.0.0.1:28080/api/health
curl -s https://yts.cool/api/health
```

> **502?** Caddy w Dockerze nie widzi `127.0.0.1` hosta VPS. Skrypt mapuje to na `host.docker.internal`.

Tunnel musi być cały czas otwarty (albo `autossh` + systemd).

---

## 3. Test

```bash
curl -s https://yts.cool/api/health
# worker: "home"
```

Potem analyze / download na stronie.

---

## Uwagi

| Temat | Co wiedzieć |
|-------|-------------|
| PC wyłączony | Strona nie działa — backend jest u Ciebie |
| Upload | Plik idzie: YouTube → PC → VPS → użytkownik (2× transfer na VPS przy dużych plikach) |
| PO Token / proxy | Na domowym IP zwykle **nie potrzebne** |
| Cookies | `YTDOWN_COOKIES_BROWSER=chrome` wystarczy lokalnie |
| Bezpieczeństwo | Używaj Tailscale lub tunelu tylko na `127.0.0.1` po stronie VPS, nie wystawiaj :8080 na publiczne IP domu |

---

## Autostart (opcjonalnie)

Na PC — systemd user service lub `tmux` + `start-home.sh`.

Tunel SSH — `autossh` w cronie przy logowaniu.
