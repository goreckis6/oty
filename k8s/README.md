# YTDown na Kubernetes

## Co jest w kontenerze

- Python 3.12 + FastAPI + uvicorn + yt-dlp
- ffmpeg (ze scalania wideo+audio)
- frontend statyczny

Obraz budowany z `Dockerfile` w katalogu głównym.

## Wymagania klastra

- Kubernetes 1.24+
- Ingress controller (opcjonalnie, np. nginx-ingress)
- Dostęp do rejestru obrazów (GHCR, Docker Hub, prywatny registry)

## 1. Zbuduj i wypchnij obraz

### Lokalnie

```bash
docker build -t ghcr.io/TWOJ_USER/ytdown:latest .
docker push ghcr.io/TWOJ_USER/ytdown:latest
```

### GitHub Actions

Workflow `.github/workflows/docker.yml` buduje obraz przy pushu na `main` i publikuje do **GHCR** (`ghcr.io/<repo>`).

## 2. Dostosuj manifesty

W `k8s/kustomization.yaml` zmień:

```yaml
images:
  - name: ghcr.io/OWNER/ytdown
    newName: ghcr.io/TWOJ_USER/ytdown
    newTag: latest
```

W `k8s/ingress.yaml` ustaw swoją domenę (jeśli używasz Ingress).

## 3. Wdróż

```bash
kubectl apply -k k8s/
```

Sprawdź:

```bash
kubectl -n ytdown get pods
kubectl -n ytdown port-forward svc/ytdown 8080:80
# http://localhost:8080
```

## 4. Udostępnienie na zewnątrz

**Opcja A — Ingress** (zalecane)

Odkomentuj `ingress.yaml` w `kustomization.yaml`, ustaw hosta i TLS, potem:

```bash
kubectl apply -k k8s/
```

Dla nginx-ingress przy długich pobieraniach 4K dodaj adnotacje z `ingress.yaml` (`proxy-read-timeout: "600"`).

**Opcja B — LoadBalancer**

Zmień w `service.yaml`:

```yaml
spec:
  type: LoadBalancer
```

## Konfiguracja

Zmienne w `k8s/configmap.yaml`:

| Zmienna | Opis |
|---------|------|
| `YTDOWN_PORT` | port w kontenerze (8080) |
| `YTDOWN_FFMPEG_DIR` | opcjonalna ścieżka do ffmpeg |

### Cookies YouTube (Secret)

```bash
kubectl -n ytdown create secret generic ytdown-cookies \
  --from-file=cookies.txt=/sciezka/do/cookies.txt
```

W `deployment.yaml` odkomentuj volume + env:

```yaml
env:
  - name: YTDOWN_COOKIES_FILE
    value: /secrets/cookies.txt
```

## Ważne ograniczenia

1. **`replicas: 1`** — status pobierania jest w pamięci procesu. Przy wielu replikach polling może trafić na inny pod i „zgubić” zadanie.
2. **Dysk tymczasowy** — pliki pobierane do `/tmp` (emptyDir, max 10 Gi). Po wysłaniu do użytkownika są usuwane.
3. **Pamięć** — 4K wymaga więcej RAM; domyślny limit to 2 Gi (edytuj `deployment.yaml`).

## Aktualizacja wersji

```bash
# nowy tag obrazu
kubectl -n ytdown set image deployment/ytdown ytdown=ghcr.io/TWOJ_USER/ytdown:v1.2.3
kubectl -n ytdown rollout status deployment/ytdown
```

## Struktura plików

```
k8s/
├── namespace.yaml
├── configmap.yaml
├── deployment.yaml
├── service.yaml
├── ingress.yaml      # opcjonalnie
└── kustomization.yaml
```
