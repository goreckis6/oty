# Migracja na nowy serwer VPS

Przeniesienie **yts.cool** (lub innej domeny) ze starego VPS na nowy **bez utraty bazy filmów** i plików z panelu admina.

## Co jest przenoszone

| Ścieżka na VPS | Zawartość |
|----------------|-----------|
| `backend/data/movies.db` | Baza filmów + ustawienia (scraping, branding w DB) |
| `backend/data/*` | Pozostałe dane scrape |
| `public/uploads/` | Logo, uploady z panelu |
| `public/downloads/` | Pliki do pobrania |
| `public/.well-known/` | Weryfikacje ACME / inne |
| `public/*.html` (oprócz `index.html`) | Pliki Google/Bing z panelu |
| `public/*.xml`, `public/*.txt` | Niestandardowy sitemap/robots (jeśli dodane ręcznie) |

**Nie trzeba przenosić:** certyfikatów Caddy (Let's Encrypt wyda nowe na nowym IP po przełączeniu DNS).

**Zostaje w GitHub Secrets** (te same wartości, zmieniasz tylko `DEPLOY_HOST`):

- `DEPLOY_SSH_KEY`, `DEPLOY_USER`, `DEPLOY_PORT`, `DEPLOY_PATH`
- `DOMAIN`, `ACME_EMAIL`
- `ADMIN_USER`, `ADMIN_PASSWORD`, `JWT_SECRET`
- `DATA_SOURCE`, `SITE_NAME`, `SITE_TAGLINE`, …

---

## Plan migracji (kolejność)

```
1. Nowy VPS — bootstrap (Docker, katalogi, firewall)
2. Klucz SSH dla GitHub Actions na nowym serwerze
3. migrate-data.sh — kopia danych ze starego → nowy
4. GitHub Secret DEPLOY_HOST → IP nowego serwera
5. Deploy (Actions lub push main)
6. Test przez IP (--resolve), bez zmiany DNS
7. DNS A → nowy IP
8. shutdown-old-server.sh na starym VPS
```

---

## Krok 1 — Bootstrap nowego serwera

Na **nowym** VPS (jako root):

```bash
# Sklonuj repo tymczasowo albo skopiuj sam skrypt:
git clone https://github.com/goreckis6/oty.git /tmp/oty
bash /tmp/oty/deploy/scripts/bootstrap-server.sh
```

Albo po pierwszym deployu rsync skrypt już będzie w `/opt/ytdown`.

---

## Krok 2 — Klucz SSH dla GitHub Actions

Na **nowym** serwerze:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/deploy_key -N ""
cat ~/.ssh/deploy_key.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
cat ~/.ssh/deploy_key   # cała zawartość → GitHub Secret DEPLOY_SSH_KEY
```

Jeśli używasz **tego samego** klucza co na starym serwerze — wystarczy dodać ten sam publiczny klucz do `authorized_keys` na nowym VPS.

---

## Krok 3 — Migracja danych (ze starego na nowy)

Z **laptopa** (SSH do obu serwerów):

```bash
cd /path/to/ytdown   # lub sklonuj repo

OLD_HOST=167.233.112.233    # IP starego VPS
NEW_HOST=NOWE.IP.TUTAJ      # IP nowego VPS
SSH_KEY=~/.ssh/twoj_klucz   # opcjonalnie

bash deploy/scripts/migrate-data.sh
```

Skrypt rsyncuje `movies.db`, uploady i pliki admina. Na końcu sprawdza integralność SQLite i liczbę filmów.

---

## Krok 4 — GitHub Secrets

W repo **Settings → Secrets and variables → Actions** zmień:

| Secret | Akcja |
|--------|--------|
| `DEPLOY_HOST` | **Nowy IP** serwera |
| `DEPLOY_SSH_KEY` | Klucz prywatny działający na nowym VPS |
| `DEPLOY_USER` | Zwykle bez zmian (`root`) |
| `DOMAIN` | Bez zmian (`yts.cool`) |
| Pozostałe | Bez zmian |

---

## Krok 5 — Deploy na nowy serwer

**Actions → Deploy → Run workflow**  
albo:

```bash
git push origin main
```

Workflow zrobi `rsync` kodu (nie nadpisze `movies.db` — katalog `backend/data/` jest wykluczony) i uruchomi `deploy.sh`.

---

## Krok 6 — Test przed zmianą DNS

Z laptopa (podstaw swój IP i domenę):

```bash
NEW_IP=NOWE.IP.TUTAJ
DOMAIN=yts.cool

curl -sk --resolve "${DOMAIN}:443:${NEW_IP}" "https://${DOMAIN}/api/v1/health"
curl -sk --resolve "${DOMAIN}:443:${NEW_IP}" "https://${DOMAIN}/api/v1/list_movies.json?limit=1" | head -c 300
curl -sk --resolve "${DOMAIN}:443:${NEW_IP}" "https://${DOMAIN}/" | head -c 200
```

Oczekiwane: JSON ze `"status"` / `"movie_count"` oraz HTML z `<!DOCTYPE html`.

---

## Krok 7 — Przełączenie DNS

U rejestratora domeny:

```
yts.cool  A  →  NOWE.IP.TUTAJ
```

TTL najlepiej wcześniej obniżyć (np. 300 s), żeby propagacja była szybka.

Po propagacji sprawdź:

```bash
curl -s "https://yts.cool/api/v1/health"
```

---

## Krok 8 — Wyłączenie starego serwera

Gdy nowy działa i DNS wskazuje na nowy IP, na **starym** VPS:

```bash
bash /opt/ytdown/deploy/scripts/shutdown-old-server.sh
```

Skrypt:
- wyłącza `ytdown.service`
- zatrzymuje kontenery Docker
- **nie kasuje** `movies.db` ani plików (backup na starym dysku)

Możesz zostawić stary VPS wyłączony jako backup przez kilka dni, potem usunąć.

---

## Autostart po reboot (nowy serwer)

Każdy udany deploy instaluje `ytdown.service` — po restarcie nowego VPS strona wstanie sama (`docker` + `systemctl enable ytdown`).

Sprawdzenie:

```bash
systemctl is-enabled docker ytdown
docker ps
```

---

## Rozwiązywanie problemów

| Problem | Co zrobić |
|---------|-----------|
| Deploy łączy się ze starym IP | Zaktualizuj `DEPLOY_HOST` w Secrets |
| Pusta strona / brak filmów | Uruchom ponownie `migrate-data.sh`, sprawdź rozmiar `movies.db` |
| Błąd TLS / certyfikat | DNS musi wskazywać na nowy IP; `ACME_EMAIL` ustawiony w Secrets |
| `Permission denied (publickey)` | Dodaj klucz z `DEPLOY_SSH_KEY` do `authorized_keys` na nowym VPS |
| Stary serwer nadal odpowiada | Sprawdź DNS (`dig yts.cool`) i cache przeglądarki |

---

## Szybka checklista

- [ ] Nowy VPS: `bootstrap-server.sh`
- [ ] SSH klucz w `authorized_keys` na nowym VPS
- [ ] `migrate-data.sh` — `movies.db` + pliki
- [ ] GitHub: `DEPLOY_HOST` = nowy IP
- [ ] Deploy workflow — zielony
- [ ] Test `--resolve` na nowy IP
- [ ] DNS A → nowy IP
- [ ] `shutdown-old-server.sh` na starym VPS
