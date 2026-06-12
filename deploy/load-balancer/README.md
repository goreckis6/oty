# Load balancer + wiele maszyn (bez Redis)

## Zasada

Job ID zawiera prefiks workera: `w1-a1b2c3…`, `w2-…`

| Endpoint | Routing |
|----------|---------|
| `POST /api/download/start` | round-robin → dowolny worker |
| `GET /api/download/status/{job_id}` | nginx → worker z prefiksu |
| `GET /api/download/file/{job_id}` | nginx → worker z prefiksu (plik na jego dysku) |

**Bez sticky sessions, bez ip_hash.** NAT / mobilne IP nie psują routingu.

## Architektura

```
Użytkownicy → nginx (LB) → w1 / w2 / w3 (Docker, WORKER_ID=wN)
                ↑
         jeden punkt awarii — na małą skalę OK;
         przy rozbudowie: managed LB (Hetzner) lub 2× nginx
```

> **Cloudflare:** nie proxuj dużych plików wideo przez darmowy plan — ryzyko naruszenia ToS i limitów.

## Dziś: jedna maszyna

nginx i worker na tym samym VPS. Config: `deploy/nginx/ytdown.conf`

```bash
sudo bash deploy/vps-setup.sh
rsync ... root@SERWER:/opt/ytdown/
ssh root@SERWER 'cd /opt/ytdown && docker compose up -d --build'
```

- Port **80** → nginx (publiczny)
- Port **8082** → app tylko `127.0.0.1` (za firewallem)
- Pliki w `./downloads/`

## Rozbudowa: +worker w2

1. Nowy VPS, `WORKER_ID=w2` w `.env` lub compose:
   ```yaml
   environment:
     WORKER_ID: w2
   ports:
     - "10.0.0.2:8082:8080"   # prywatne IP, nie localhost
   ```
2. `ufw allow from IP_LB to any port 8082`
3. W `deploy/nginx/ytdown.conf` odkomentuj:
   ```nginx
   ~/(?:status|file)/w2-  10.0.0.2:8082;
   server 10.0.0.2:8082 ...;
   ```
4. `nginx -t && systemctl reload nginx`

Backend i frontend **bez zmian**.

## LB jako osobny VPS

Przenieś `ytdown.conf` na maszynę LB. W `map` i `upstream` zamień `127.0.0.1` na prywatne IP w1.

## Deploy bez zabijania wszystkich jobów

```bash
./deploy/scripts/rolling-deploy.sh root@10.0.0.1 root@10.0.0.2
```

Lepsza wersja: przed restartem zakomentuj workera w `upstream`, `nginx -s reload`, poczekaj, przebuduj, odkomentuj.

## Sprzątanie dysku

Cron (instalowany przez `vps-setup.sh`):

```bash
# co godzinę, pliki starsze niż 2h
0 * * * * /opt/ytdown/deploy/scripts/cleanup-downloads.sh
```

## Health check

`GET /api/health` → **503** gdy < 2 GB wolnego na `/downloads`.  
nginx (pasywnie, `max_fails=2`) przestaje wysyłać nowe `start` na pełny dysk.

## Ograniczenia (świadome)

| | |
|--|--|
| Restart workera | kasuje jego joby w RAM + pliki w toku |
| LB | pojedynczy punkt awarii |
| Skala 100+ | wtedy Redis + kolejka + S3 |

## Generowanie nginx dla N workerów

Przy wielu maszynach edytuj `map` i `upstream` w jednym pliku — albo wygeneruj skryptem z listy IP.
