const $ = (sel) => document.querySelector(sel);

const form = $("#downloadForm");
const urlInput = $("#urlInput");
const clearBtn = $("#clearBtn");
const submitBtn = $("#submitBtn");
const btnLabel = submitBtn.querySelector(".btn-label");
const btnSpinner = submitBtn.querySelector(".btn-spinner");
const results = $("#results");
const videoThumb = $("#videoThumb");
const videoTitle = $("#videoTitle");
const videoMeta = $("#videoMeta");
const formatsGrid = $("#formatsGrid");
const newDownloadBtn = $("#newDownloadBtn");
const toast = $("#toast");
const navToggle = $("#navToggle");
const nav = document.querySelector(".nav");
const statusPanel = $("#statusPanel");
const statusSpinner = $("#statusSpinner");
const statusTitle = $("#statusTitle");
const statusFill = $("#statusFill");
const statusMessage = $("#statusMessage");
const statusMeta = $("#statusMeta");

let currentVideo = null;
let pollTimer = null;

function showToast(message, isError = false) {
  toast.textContent = message;
  toast.className = `toast toast--visible${isError ? " toast--error" : ""}`;
  toast.hidden = false;
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => {
    toast.classList.remove("toast--visible");
    setTimeout(() => { toast.hidden = true; }, 300);
  }, 5000);
}

function setLoading(loading) {
  submitBtn.disabled = loading;
  btnLabel.hidden = loading;
  btnSpinner.hidden = !loading;
}

function showStatus({ title, message, meta = "", percent = null, mode = "loading" }) {
  statusPanel.hidden = false;
  statusTitle.textContent = title;
  statusMessage.textContent = message;
  statusMeta.textContent = meta;
  statusPanel.classList.remove("status-panel--done", "status-panel--error", "status-panel--indeterminate");

  if (mode === "error") {
    statusPanel.classList.add("status-panel--error");
    statusFill.style.width = "0%";
    return;
  }
  if (mode === "done") {
    statusPanel.classList.add("status-panel--done");
    statusFill.style.width = "100%";
    return;
  }
  if (percent === null) {
    statusPanel.classList.add("status-panel--indeterminate");
    statusFill.style.width = "40%";
  } else {
    statusFill.style.width = `${Math.min(100, Math.max(0, percent))}%`;
  }
}

function hideStatus() {
  statusPanel.hidden = true;
  if (typeof pollTimer === "function") pollTimer();
  pollTimer = null;
}

function formatDuration(seconds) {
  if (!seconds) return "";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatFilesize(bytes) {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let i = 0;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i++;
  }
  return `${size.toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
}

function parseError(data, fallback) {
  const detail = data?.detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join(", ");
  return detail || fallback;
}

urlInput.addEventListener("input", () => {
  clearBtn.hidden = !urlInput.value;
});

clearBtn.addEventListener("click", () => {
  urlInput.value = "";
  clearBtn.hidden = true;
  urlInput.focus();
});

navToggle.addEventListener("click", () => {
  nav.classList.toggle("nav--open");
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = urlInput.value.trim();
  if (!url) return;

  setLoading(true);
  results.hidden = true;
  showStatus({
    title: "Analizuję link…",
    message: "Pobieram informacje o filmie z YouTube.",
    mode: "loading",
  });

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(parseError(data, "Nie udało się przeanalizować filmu."));

    currentVideo = data;
    renderResults(data);
    results.hidden = false;
    hideStatus();
    results.scrollIntoView({ behavior: "smooth", block: "nearest" });
    showToast("Wybierz format do pobrania.");
  } catch (err) {
    showStatus({
      title: "Błąd",
      message: err.message,
      mode: "error",
    });
    showToast(err.message, true);
  } finally {
    setLoading(false);
  }
});

function renderResults(data) {
  videoThumb.src = data.thumbnail || "";
  videoThumb.alt = data.title;
  videoTitle.textContent = data.title;

  const meta = [];
  if (data.uploader) meta.push(data.uploader);
  if (data.duration) meta.push(formatDuration(data.duration));
  videoMeta.textContent = meta.join(" · ");

  formatsGrid.innerHTML = "";
  const videoFormats = data.formats.filter((f) => f.kind === "video");
  const audioFormats = data.formats.filter((f) => f.kind === "audio");

  const addGroup = (title, formats) => {
    if (!formats.length) return;
    const heading = document.createElement("h4");
    heading.className = "formats__group-title";
    heading.textContent = title;
    formatsGrid.appendChild(heading);

    const grid = document.createElement("div");
    grid.className = "formats__grid-inner";
    for (const fmt of formats) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "format-btn";
      btn.innerHTML = `
        <span class="format-btn__label">${fmt.label}</span>
        <span class="format-btn__meta">${fmt.ext}${fmt.filesize ? " · " + formatFilesize(fmt.filesize) : ""}</span>
      `;
      btn.addEventListener("click", () => downloadFormat(fmt, btn));
      grid.appendChild(btn);
    }
    formatsGrid.appendChild(grid);
  };

  addGroup("Wideo", videoFormats);
  addGroup("Audio", audioFormats);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function startFileDownload(jobId) {
  const iframe = document.createElement("iframe");
  iframe.style.display = "none";
  iframe.src = `/api/download/file/${jobId}`;
  document.body.appendChild(iframe);
  setTimeout(() => iframe.remove(), 60000);
}

async function pollJob(jobId, fmt) {
  const startedAt = Date.now();
  let polling = true;

  pollTimer = () => { polling = false; };

  while (polling) {
    const res = await fetch(`/api/download/status/${jobId}`);
    const data = await res.json();
    if (!res.ok) throw new Error(parseError(data, "Błąd statusu pobierania."));

    const elapsed = Math.floor((Date.now() - startedAt) / 1000);
    const elapsedStr = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")}`;
    const metaParts = [`Czas: ${elapsedStr}`];
    if (data.speed) metaParts.push(`Prędkość: ${data.speed}`);
    if (data.eta) metaParts.push(`Pozostało: ${data.eta}`);

    if (data.status === "done") {
      showStatus({
        title: "Pobieranie gotowe",
        message: "Zapisuję plik na Twoim urządzeniu…",
        mode: "done",
      });
      return data;
    }

    if (data.status === "error") {
      throw new Error(data.message || "Pobieranie nie powiodło się.");
    }

    const isLarge = fmt.id === "q:2160" || fmt.id === "q:1440" || (fmt.filesize && fmt.filesize > 200 * 1024 * 1024);
    const message = data.status === "processing"
      ? "Scalanie wideo i audio… (przy 4K może potrwać kilka minut)"
      : (data.message || "Pobieram plik z YouTube…") + (isLarge && data.percent < 5 ? " — duży plik, to normalne że trwa dłużej" : "");

    showStatus({
      title: data.status === "processing" ? "Przetwarzanie" : "Pobieranie w toku",
      message,
      meta: metaParts.join(" · "),
      percent: data.percent,
      mode: "loading",
    });

    await sleep(1000);
  }

  throw new Error("Pobieranie anulowane.");
}

async function downloadFormat(fmt, btn) {
  if (!currentVideo) return;

  btn.classList.add("format-btn--loading");
  btn.disabled = true;

  const is4k = fmt.id === "q:2160";
  showStatus({
    title: "Przygotowuję pobieranie",
    message: is4k
      ? `${fmt.label} — 4K to duży plik (200+ MB), pobieranie może zająć kilka minut. Strona pozostaje aktywna.`
      : `Format: ${fmt.label} (${fmt.ext})`,
    mode: "loading",
  });
  statusPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });

  try {
    const res = await fetch("/api/download/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: currentVideo.url,
        format_id: fmt.id,
        ext: fmt.ext,
      }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(parseError(data, "Nie udało się rozpocząć pobierania."));

    await pollJob(data.job_id, fmt);

    startFileDownload(data.job_id);

    showStatus({
      title: "Sukces!",
      message: "Plik powinien pojawić się w folderze Pobrane.",
      mode: "done",
    });
    showToast("Pobieranie zakończone!");
    setTimeout(hideStatus, 6000);
  } catch (err) {
    showStatus({
      title: "Błąd pobierania",
      message: err.message,
      mode: "error",
    });
    showToast(err.message, true);
  } finally {
    btn.disabled = false;
    btn.classList.remove("format-btn--loading");
  }
}

newDownloadBtn.addEventListener("click", () => {
  hideStatus();
  results.hidden = true;
  urlInput.value = "";
  clearBtn.hidden = true;
  currentVideo = null;
  urlInput.focus();
  window.scrollTo({ top: 0, behavior: "smooth" });
});
