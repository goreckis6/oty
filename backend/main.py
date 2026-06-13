import os
import re
import shutil
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import yt_dlp
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
FFMPEG_DIR = Path(__file__).resolve().parent.parent / "bin"
DOWNLOADS_DIR = Path(os.environ.get("YTDOWN_DOWNLOADS_DIR", "/downloads"))
WORKER_ID = os.environ.get("WORKER_ID", "w1")
MIN_FREE_BYTES = int(os.environ.get("YTDOWN_MIN_FREE_GB", "2")) * 1024**3

DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
YOUTUBE_URL_RE = re.compile(
    r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|music\.youtube\.com)/.+",
    re.IGNORECASE,
)

# Chrome on Windows — domyślna symulacja przeglądarki (yt-dlp + nagłówki HTTP).
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_YOUTUBE_CLIENTS = "android_vr,web,web_safari,android"
COOKIE_YOUTUBE_CLIENTS = "web,web_safari,tv_embedded,mweb"
COOKIE_FILE_CANDIDATES = (
    "/etc/ytdown/cookies.txt",
    "/app/secrets/cookies.txt",
    str(Path(__file__).resolve().parent.parent / "secrets" / "cookies.txt"),
)

app = FastAPI(title="YTDown", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()


class AnalyzeRequest(BaseModel):
    url: str = Field(..., min_length=10)


class DownloadStartRequest(BaseModel):
    url: str = Field(..., min_length=10)
    format_id: str
    ext: str = "mp4"


def new_job_id() -> str:
    return f"{WORKER_ID}-{uuid.uuid4().hex}"


def job_work_dir(job_id: str) -> Path:
    path = DOWNLOADS_DIR / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_url(url: str) -> str:
    url = url.strip()
    if not YOUTUBE_URL_RE.match(url):
        raise HTTPException(status_code=400, detail="Wpisz poprawny link YouTube.")
    return url


def friendly_error(message: str) -> str:
    lower = message.lower()
    if "player response" in lower or "no longer valid" in lower:
        if _resolve_cookie_file():
            if "no longer valid" in lower:
                return (
                    "Cookies YouTube wygasły. Wyeksportuj świeże cookies z Chrome "
                    "(Get cookies.txt LOCALLY, będąc na youtube.com) i zaktualizuj na serwerze."
                )
            return "YouTube odrzucił żądanie mimo cookies. Wyeksportuj świeże cookies z zalogowanej sesji."
        return (
            "YouTube blokuje serwer VPS. Wyeksportuj cookies z Chrome (Get cookies.txt LOCALLY) "
            "i wgraj na serwer jako /opt/ytdown/secrets/cookies.txt"
        )
    if "challenge solving" in lower and not _detect_js_runtimes():
        return (
            "Brak Node.js/Deno dla yt-dlp. Na serwerze: apt install nodejs && docker compose up -d --build"
        )
    if "Sign in to confirm" in message or "bot" in message.lower():
        if _resolve_cookie_file():
            return (
                "Cookies YouTube zostały unieważnione (rotacja konta). Wyeksportuj świeże: "
                "otwórz youtube.com w oknie incognito, NIE przeglądaj dalej, wyeksportuj cookies "
                "(Get cookies.txt LOCALLY) i zamknij okno bez wylogowania. Wgraj na serwer."
            )
        if _pot_provider_url() and not _pot_provider_reachable():
            return (
                "Serwer PO Token (bgutil-provider) nie odpowiada. "
                "Sprawdź: docker compose ps && docker compose logs bgutil-provider"
            )
        if not _pot_provider_url():
            return (
                "YouTube zablokował pobieranie. W Dockerze włącz bgutil-provider "
                "(YTDOWN_POT_PROVIDER_URL) lub dodaj cookies na serwerze."
            )
        return (
            "YouTube nadal blokuje VPS mimo PO Token. Dodaj świeże cookies "
            "jako /opt/ytdown/secrets/cookies.txt (opcjonalnie razem z PO Token)."
        )
    if "ffmpeg" in message.lower() or "ffprobe" in message.lower():
        return "Brak ffmpeg. Zainstaluj: sudo apt install ffmpeg"
    if message.startswith("ERROR:"):
        message = message[6:].strip()
    return message[:300]


def _resolve_cookie_file() -> str | None:
    explicit = os.environ.get("YTDOWN_COOKIES_FILE")
    source: Path | None = None
    if explicit and Path(explicit).is_file():
        source = Path(explicit)
    else:
        for candidate in COOKIE_FILE_CANDIDATES:
            path = Path(candidate)
            if path.is_file():
                source = path
                break
    if not source:
        return None
    if os.access(source, os.W_OK):
        return str(source)
    # yt-dlp zapisuje cookies przy zamknięciu — kopia na zapisywalny dysk (Docker :ro mount).
    cache = Path(os.environ.get("YTDOWN_COOKIE_CACHE", "/tmp/ytdown_youtube_cookies.txt"))
    if not cache.exists() or cache.stat().st_mtime < source.stat().st_mtime:
        shutil.copy2(source, cache)
    return str(cache)


def _runtime_binary_paths(runtime: str) -> tuple[str, ...]:
    env_path = os.environ.get(f"YTDOWN_{runtime.upper()}_PATH", "").strip()
    if env_path:
        return (env_path,)
    if runtime == "node":
        return ("/usr/bin/node", "/usr/local/bin/node", "node", "nodejs")
    if runtime == "deno":
        return ("/usr/local/bin/deno", "/usr/bin/deno", "deno")
    return (runtime,)


def _runtime_available(runtime: str) -> bool:
    for candidate in _runtime_binary_paths(runtime):
        if "/" in candidate:
            if Path(candidate).is_file():
                return True
        elif shutil.which(candidate):
            return True
    return False


def _detect_js_runtimes() -> dict[str, dict]:
    explicit = os.environ.get("YTDOWN_JS_RUNTIMES", "").strip()
    if explicit:
        names = [name.strip().lower() for name in explicit.split(",") if name.strip()]
    else:
        names = ["deno", "node"]

    runtimes: dict[str, dict] = {}
    for runtime in names:
        if _runtime_available(runtime):
            config: dict[str, str] = {}
            for candidate in _runtime_binary_paths(runtime):
                if "/" in candidate and Path(candidate).is_file():
                    config["path"] = candidate
                    break
            runtimes[runtime] = config
    return runtimes


def _remote_components() -> list[str]:
    raw = os.environ.get("YTDOWN_REMOTE_COMPONENTS", "ejs:github,ejs:npm")
    if not raw or raw.lower() in ("none", "off", "false"):
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _pot_provider_url() -> str | None:
    raw = os.environ.get("YTDOWN_POT_PROVIDER_URL", "").strip()
    if not raw or raw.lower() in ("none", "off", "false", "0"):
        return None
    return raw.rstrip("/")


def _pot_provider_reachable() -> bool:
    url = _pot_provider_url()
    if not url:
        return False
    try:
        with urllib.request.urlopen(f"{url}/ping", timeout=2) as resp:
            return resp.status < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _youtube_extractor_args(player_clients: list[str]) -> dict[str, Any]:
    args: dict[str, Any] = {
        "youtube": {
            "player_client": player_clients,
        }
    }
    pot_url = _pot_provider_url()
    if pot_url:
        args["youtubepot-bgutilhttp"] = {"base_url": pot_url}
    return args


def _youtube_player_clients() -> list[str]:
    raw = os.environ.get("YTDOWN_YOUTUBE_CLIENTS") or _default_youtube_clients()
    return [client.strip() for client in raw.split(",") if client.strip()]


def _default_youtube_clients() -> str:
    if _resolve_cookie_file() or os.environ.get("YTDOWN_COOKIES_BROWSER"):
        return COOKIE_YOUTUBE_CLIENTS
    return DEFAULT_YOUTUBE_CLIENTS


def _youtube_client_sets() -> list[str]:
    primary = os.environ.get("YTDOWN_YOUTUBE_CLIENTS") or _default_youtube_clients()
    fallbacks = (
        COOKIE_YOUTUBE_CLIENTS,
        "tv_embedded,web",
        "web,android,ios",
        DEFAULT_YOUTUBE_CLIENTS,
    )
    client_sets = [primary]
    for fallback in fallbacks:
        if fallback not in client_sets:
            client_sets.append(fallback)
    return client_sets


def _browser_http_headers() -> dict[str, str]:
    return {
        "User-Agent": os.environ.get("YTDOWN_USER_AGENT", CHROME_USER_AGENT),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": os.environ.get("YTDOWN_ACCEPT_LANGUAGE", "en-US,en;q=0.9,pl;q=0.8"),
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }


def base_ydl_opts(job_id: str | None = None) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "force_ipv4": os.environ.get("YTDOWN_FORCE_IPV4", "1") != "0",
        "extractor_args": _youtube_extractor_args(_youtube_player_clients()),
    }
    # Własne nagłówki psują ekstrakcję z cookies — yt-dlp ma lepsze domyślne.
    if not _resolve_cookie_file() and not os.environ.get("YTDOWN_COOKIES_BROWSER"):
        opts["http_headers"] = _browser_http_headers()

    js_runtimes = _detect_js_runtimes()
    if js_runtimes:
        opts["js_runtimes"] = js_runtimes

    remote_components = _remote_components()
    if remote_components:
        opts["remote_components"] = remote_components

    sleep_requests = os.environ.get("YTDOWN_SLEEP_INTERVAL_REQUESTS")
    if sleep_requests:
        opts["sleep_interval_requests"] = float(sleep_requests)
    if job_id:

        def progress_hook(data: dict[str, Any]) -> None:
            with jobs_lock:
                job = jobs.get(job_id)
                if not job:
                    return
                status = data.get("status")
                if status == "downloading":
                    total = data.get("total_bytes") or data.get("total_bytes_estimate")
                    downloaded = data.get("downloaded_bytes") or 0
                    percent = round(downloaded / total * 100, 1) if total else None
                    job.update(
                        {
                            "status": "downloading",
                            "percent": percent,
                            "speed": (data.get("_speed_str") or "").strip(),
                            "eta": (data.get("_eta_str") or "").strip(),
                            "message": f"Pobieranie z YouTube… {(data.get('_percent_str') or '').strip()}".strip(),
                        }
                    )
                elif status == "finished":
                    job.update(
                        {
                            "status": "processing",
                            "percent": None,
                            "message": "Scalanie wideo i audio…",
                        }
                    )

        def postprocessor_hook(data: dict[str, Any]) -> None:
            if data.get("postprocessor") == "Merger":
                with jobs_lock:
                    job = jobs.get(job_id)
                    if job:
                        job.update(
                            {
                                "status": "processing",
                                "percent": None,
                                "message": "Scalanie wideo i audio (4K może potrwać kilka minut)…",
                            }
                        )

        opts["progress_hooks"] = [progress_hook]
        opts["postprocessor_hooks"] = [postprocessor_hook]

    cookies_file = _resolve_cookie_file()
    if cookies_file:
        opts["cookiefile"] = cookies_file
    else:
        cookies_browser = os.environ.get("YTDOWN_COOKIES_BROWSER")
        if cookies_browser:
            opts["cookiesfrombrowser"] = (cookies_browser,)
    ffmpeg_dir = os.environ.get("YTDOWN_FFMPEG_DIR")
    if ffmpeg_dir:
        opts["ffmpeg_location"] = ffmpeg_dir
    elif (FFMPEG_DIR / "ffmpeg").exists():
        opts["ffmpeg_location"] = str(FFMPEG_DIR)
    return opts


QUALITY_TIERS = (2160, 1440, 1080, 720, 480, 360, 240)


def _has_video(fmt: dict[str, Any]) -> bool:
    return fmt.get("vcodec") not in (None, "none")


def _has_audio(fmt: dict[str, Any]) -> bool:
    return fmt.get("acodec") not in (None, "none")


def _fmt_size(fmt: dict[str, Any]) -> int | None:
    return fmt.get("filesize") or fmt.get("filesize_approx")


def _merge_format_string(height: int) -> str:
    return (
        f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={height}]+bestaudio/"
        f"best[height<={height}]/best"
    )


def extract_formats(info: dict[str, Any]) -> list[dict[str, Any]]:
    raw = info.get("formats") or []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    video_heights: set[int] = set()
    progressive_by_height: dict[int, dict[str, Any]] = {}
    video_only_by_height: dict[int, dict[str, Any]] = {}
    audio_formats: list[dict[str, Any]] = []

    for fmt in raw:
        if not _has_video(fmt) and _has_audio(fmt):
            if fmt.get("ext") in ("m4a", "webm", "opus"):
                audio_formats.append(fmt)
            continue

        height = fmt.get("height")
        if not height or not _has_video(fmt):
            continue

        video_heights.add(height)
        if _has_audio(fmt):
            current = progressive_by_height.get(height)
            if not current or (_fmt_size(fmt) or 0) > (_fmt_size(current) or 0):
                progressive_by_height[height] = fmt
        else:
            current = video_only_by_height.get(height)
            prefer_mp4 = fmt.get("ext") == "mp4"
            current_mp4 = current and current.get("ext") == "mp4"
            if not current or (prefer_mp4 and not current_mp4) or (
                prefer_mp4 == current_mp4 and (_fmt_size(fmt) or 0) > (_fmt_size(current) or 0)
            ):
                video_only_by_height[height] = fmt

    best_audio = max(audio_formats, key=lambda f: f.get("abr") or 0, default=None)
    audio_size = _fmt_size(best_audio) if best_audio else None

    max_height = max(video_heights) if video_heights else 0
    available_tiers = [h for h in QUALITY_TIERS if h <= max_height]

    for height in available_tiers:
        progressive = progressive_by_height.get(height)
        if progressive:
            fmt_id = progressive.get("format_id")
            key = f"id:{fmt_id}"
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "id": key,
                    "label": f"{height}p · MP4",
                    "ext": "mp4",
                    "kind": "video",
                    "filesize": _fmt_size(progressive),
                }
            )
            continue

        if not any(vh <= height for vh in video_heights):
            continue

        key = f"q:{height}"
        if key in seen:
            continue
        seen.add(key)

        best_video = None
        for vh, fmt in video_only_by_height.items():
            if vh <= height and (not best_video or vh > best_video.get("height", 0)):
                best_video = fmt

        filesize = None
        if best_video and audio_size:
            filesize = (_fmt_size(best_video) or 0) + audio_size

        result.append(
            {
                "id": key,
                "label": f"{height}p · MP4",
                "ext": "mp4",
                "kind": "video",
                "filesize": filesize,
            }
        )

    if best_audio:
        abr = best_audio.get("abr")
        result.append(
            {
                "id": "audio:best",
                "label": f"Audio · {int(abr)} kbps" if abr else "Audio · najlepsza jakość",
                "ext": best_audio.get("ext", "m4a"),
                "kind": "audio",
                "filesize": audio_size,
            }
        )

    result.append(
        {
            "id": "audio:mp3",
            "label": "MP3 · 192 kbps",
            "ext": "mp3",
            "kind": "audio",
            "filesize": audio_size,
        }
    )

    return result


def resolve_format_selector(format_id: str, ext: str) -> tuple[str, dict[str, Any]]:
    extra: dict[str, Any] = {}

    if format_id.startswith("q:"):
        height = int(format_id[2:])
        extra["merge_output_format"] = "mp4"
        return _merge_format_string(height), extra

    if format_id.startswith("id:"):
        return format_id[3:], extra

    if format_id == "audio:mp3":
        extra["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
        return "bestaudio/best", extra

    if format_id == "audio:best":
        return "bestaudio/best", extra

    if ext == "mp3":
        extra["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
        return "bestaudio/best", extra

    return format_id, extra


def build_download_opts(url: str, format_id: str, ext: str, tmp_dir: str, job_id: str | None) -> dict[str, Any]:
    selector, extra = resolve_format_selector(format_id, ext)
    ydl_opts: dict[str, Any] = {
        **base_ydl_opts(job_id),
        "format": selector,
        "outtmpl": str(Path(tmp_dir) / "%(title).200B.%(ext)s"),
        **extra,
    }
    # Własne nagłówki psują ekstrakcję z cookies — używaj ich tylko bez cookies.
    if not _resolve_cookie_file() and not os.environ.get("YTDOWN_COOKIES_BROWSER"):
        headers = _browser_http_headers()
        headers["Referer"] = "https://www.youtube.com/"
        headers["Origin"] = "https://www.youtube.com"
        ydl_opts["http_headers"] = headers
    if ext in ("mp4", "webm", "mkv") and "merge_output_format" not in ydl_opts:
        ydl_opts["merge_output_format"] = ext
    return ydl_opts


YOUTUBE_CLIENT_FALLBACKS = (
    "web,web_safari,tv_embedded,mweb",
    "tv_embedded,web",
    "web,android,ios",
)


def extract_youtube_info(url: str, job_id: str | None = None, download: bool = False) -> dict[str, Any]:
    client_sets = _youtube_client_sets()

    last_error: Exception | None = None
    for clients in client_sets:
        client_list = [c.strip() for c in clients.split(",") if c.strip()]
        opts = {
            **base_ydl_opts(job_id),
            "skip_download": not download,
            "extract_flat": False,
            "extractor_args": _youtube_extractor_args(client_list),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=download)
        except yt_dlp.utils.DownloadError as exc:
            last_error = exc
            if "player response" not in str(exc).lower():
                raise
    if last_error:
        raise last_error
    raise RuntimeError("Nie udało się pobrać informacji o filmie.")


def run_download_job(job_id: str, url: str, format_id: str, ext: str) -> None:
    tmp_dir = str(job_work_dir(job_id))
    try:
        with jobs_lock:
            jobs[job_id].update(
                {
                    "status": "downloading",
                    "message": "Łączenie z YouTube…",
                    "percent": 0,
                }
            )

        last_error: Exception | None = None
        info = None
        seen: set[str] = set()
        for clients in _youtube_client_sets():
            if clients in seen:
                continue
            seen.add(clients)
            client_list = [c.strip() for c in clients.split(",") if c.strip()]
            ydl_opts = build_download_opts(url, format_id, ext, tmp_dir, job_id)
            ydl_opts["extractor_args"] = _youtube_extractor_args(client_list)
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                break
            except yt_dlp.utils.DownloadError as exc:
                last_error = exc
                if "player response" not in str(exc).lower():
                    raise
        if info is None:
            raise last_error or RuntimeError("Pobieranie nie powiodło się.")

        requested = info.get("requested_downloads") or []
        if requested and requested[0].get("filepath"):
            filepath = Path(requested[0]["filepath"])
        elif info.get("_filename"):
            filepath = Path(info["_filename"])
        else:
            candidates = [p for p in Path(tmp_dir).glob("*") if p.is_file()]
            if not candidates:
                raise RuntimeError("Nie udało się zapisać pliku.")
            filepath = max(candidates, key=lambda p: p.stat().st_mtime)
        if ext == "mp3":
            mp3 = filepath.with_suffix(".mp3")
            filepath = mp3 if mp3.exists() else filepath
        if not filepath.exists():
            candidates = [p for p in Path(tmp_dir).glob("*") if p.is_file()]
            if not candidates:
                raise RuntimeError("Nie udało się zapisać pliku.")
            filepath = candidates[0]

        with jobs_lock:
            jobs[job_id].update(
                {
                    "status": "done",
                    "percent": 100,
                    "message": "Gotowe! Rozpoczynam zapis…",
                    "filepath": str(filepath),
                    "tmp_dir": tmp_dir,
                    "filename": filepath.name,
                }
            )
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        with jobs_lock:
            jobs[job_id].update(
                {
                    "status": "error",
                    "message": friendly_error(str(exc)),
                }
            )


@app.post("/api/analyze")
def analyze_video(body: AnalyzeRequest) -> dict[str, Any]:
    url = normalize_url(body.url)

    try:
        info = extract_youtube_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise HTTPException(status_code=422, detail=friendly_error(str(exc))) from exc

    if not info:
        raise HTTPException(status_code=404, detail="Nie znaleziono filmu.")

    formats = extract_formats(info)
    if not formats:
        raise HTTPException(status_code=422, detail="Brak dostępnych formatów do pobrania.")

    return {
        "title": info.get("title", "Unknown"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("channel"),
        "url": url,
        "formats": formats,
    }


@app.post("/api/download/start")
def start_download(body: DownloadStartRequest) -> dict[str, str]:
    url = normalize_url(body.url)
    job_id = new_job_id()

    with jobs_lock:
        jobs[job_id] = {
            "status": "queued",
            "percent": 0,
            "speed": "",
            "eta": "",
            "message": "Kolejkowanie pobierania…",
            "filepath": None,
            "tmp_dir": None,
            "filename": None,
        }

    thread = threading.Thread(
        target=run_download_job,
        args=(job_id, url, body.format_id, body.ext),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}


@app.get("/api/download/status/{job_id}")
def download_status(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Nie znaleziono zadania pobierania.")
        return {
            "status": job["status"],
            "percent": job.get("percent"),
            "speed": job.get("speed", ""),
            "eta": job.get("eta", ""),
            "message": job.get("message", ""),
            "filename": job.get("filename"),
        }


def cleanup_job(job_id: str) -> None:
    with jobs_lock:
        job = jobs.pop(job_id, None)
    if not job:
        return
    tmp_dir = job.get("tmp_dir")
    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.get("/api/download/file/{job_id}")
def download_file(job_id: str, background_tasks: BackgroundTasks):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Plik nie jest już dostępny.")
        if job["status"] != "done" or not job.get("filepath"):
            raise HTTPException(status_code=409, detail=job.get("message", "Pobieranie jeszcze trwa."))

        filepath = Path(job["filepath"])
        filename = job.get("filename") or filepath.name
        ext = filepath.suffix.lstrip(".") or "mp4"

    if not filepath.exists():
        cleanup_job(job_id)
        raise HTTPException(status_code=404, detail="Plik wygasł. Pobierz ponownie.")

    media_type = "audio/mpeg" if ext == "mp3" else f"video/{ext}"
    background_tasks.add_task(cleanup_job, job_id)
    return FileResponse(path=filepath, filename=filename, media_type=media_type)


@app.get("/api/health")
def health() -> dict[str, Any]:
    free = shutil.disk_usage(DOWNLOADS_DIR).free
    if free < MIN_FREE_BYTES:
        raise HTTPException(
            status_code=503,
            detail=f"low disk: {free // (1024**2)} MB free on {DOWNLOADS_DIR}",
        )
    cookie_file = _resolve_cookie_file()
    pot_url = _pot_provider_url()
    return {
        "status": "ok",
        "worker": WORKER_ID,
        "disk_free_mb": free // (1024**2),
        "youtube_cookies": bool(cookie_file or os.environ.get("YTDOWN_COOKIES_BROWSER")),
        "pot_provider": {
            "enabled": bool(pot_url),
            "url": pot_url,
            "reachable": _pot_provider_reachable() if pot_url else False,
        },
        "js_runtimes": list(_detect_js_runtimes().keys()),
        "yt_dlp_version": getattr(yt_dlp.version, "__version__", "unknown"),
    }


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
