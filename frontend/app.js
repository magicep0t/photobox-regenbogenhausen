// Photobox touch UI.
// States: live → countdown → (capture) → result → live
//         live → gallery → viewer → gallery → live

import { TEXTS, loadLanguage, saveLanguage } from "./i18n.js";

const $ = (sel) => document.querySelector(sel);
const app = $("#app");
const preview = $("#preview");
const countdownEl = $("#countdown");
const flash = $("#flash");
const resultImg = $("#result-img");
const galleryEl = $("#gallery");
const galleryGrid = $("#gallery-grid");
const viewerEl = $("#viewer");
const viewerImg = $("#viewer-img");
const viewerCounter = $("#viewer-counter");
const toast = $("#toast");
const menuButtons = $("#menu-buttons");

let config = { countdown_seconds: 3, mirror_preview: true, idle_timeout_seconds: 60, default_language: "en" };
let lang = "en";
let state = "live";
let idleTimer = null;
let toastTimer = null;
let galleryPhotos = [];
let viewerIndex = 0;
let sliding = false;

const t = (key) => TEXTS[lang][key] ?? key;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- menu ----------

const MENUS = {
  live: [
    { key: "take_photo", icon: "camera", primary: true, action: startCountdown },
    { key: "gallery", icon: "gallery", action: openGallery },
    { key: "language", icon: "language", small: true, action: toggleLanguage },
  ],
  countdown: [
    { key: "take_photo", icon: "camera", primary: true, disabled: true },
    { key: "gallery", icon: "gallery", disabled: true },
    { key: "language", icon: "language", small: true, disabled: true },
  ],
  result: [
    { key: "again", icon: "again", primary: true, action: startCountdown },
    { key: "done", icon: "done", action: goLive },
  ],
  gallery: [{ key: "back", icon: "back", primary: true, action: goLive }],
  viewer: [
    { key: "previous", icon: "prev", grow: true, action: () => step(-1), disabled: () => viewerIndex <= 0 },
    { key: "next", icon: "next", grow: true, action: () => step(1), disabled: () => viewerIndex >= galleryPhotos.length - 1 },
    { key: "gallery", icon: "gallery", small: true, action: backToGallery },
  ],
};

function renderMenu() {
  menuButtons.replaceChildren(
    ...MENUS[state].map((item) => {
      const btn = document.createElement("button");
      btn.className = "menu-btn" + (item.primary ? " primary" : "") + (item.small ? " small" : "") + (item.grow ? " grow" : "");
      btn.disabled = typeof item.disabled === "function" ? item.disabled() : !!item.disabled;
      btn.innerHTML = `<svg aria-hidden="true"><use href="#icon-${item.icon}"></use></svg><span></span>`;
      btn.querySelector("span").textContent = t(item.key);
      if (item.action) btn.addEventListener("click", item.action);
      return btn;
    }),
  );
}

function setState(next) {
  state = next;
  app.dataset.state = next;
  renderMenu();
  resetIdleTimer();
}

function applyTexts() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  renderMenu();
}

function toggleLanguage() {
  lang = lang === "en" ? "de" : "en";
  saveLanguage(lang);
  applyTexts();
}

// ---------- idle timeout ----------

function resetIdleTimer() {
  clearTimeout(idleTimer);
  if (state === "live" || state === "countdown") return;
  idleTimer = setTimeout(goLive, config.idle_timeout_seconds * 1000);
}
document.addEventListener("pointerdown", resetIdleTimer, { passive: true });

// ---------- preview ----------

function startPreview() {
  preview.src = `/api/stream?t=${Date.now()}`;
}
preview.addEventListener("error", () => {
  showToast(t("error_preview"));
  setTimeout(startPreview, 2000);
});

// tap on the live preview also starts a photo
$("#stage").addEventListener("click", (e) => {
  if (state === "live" && e.target === preview) startCountdown();
});

// ---------- photo flow ----------

async function startCountdown() {
  if (state === "countdown") return;
  setState("live"); // make sure the preview is visible
  setState("countdown");

  for (let n = config.countdown_seconds; n > 0; n--) {
    countdownEl.classList.remove("small");
    countdownEl.textContent = n;
    countdownEl.classList.remove("tick");
    void countdownEl.offsetWidth; // restart animation
    countdownEl.classList.add("tick");
    await sleep(1000);
  }

  countdownEl.textContent = t("smile");
  countdownEl.classList.add("small");
  flash.classList.remove("on");
  void flash.offsetWidth;
  flash.classList.add("on");

  try {
    const res = await fetch("/api/capture", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const photo = await res.json();
    await showResult(photo);
  } catch (err) {
    console.error("capture failed", err);
    showToast(t("error_capture"));
    setState("live");
  }
}

function showResult(photo) {
  return new Promise((resolve) => {
    resultImg.onload = resultImg.onerror = () => {
      setState("result");
      resolve();
    };
    resultImg.src = photo.url;
  });
}

function goLive() {
  viewerImg.removeAttribute("src");
  setState("live");
}

// ---------- gallery ----------

async function openGallery() {
  setState("gallery");
  galleryEl.scrollTop = 0;
  try {
    const res = await fetch("/api/photos?limit=60");
    galleryPhotos = await res.json();
    galleryEl.classList.toggle("empty", galleryPhotos.length === 0);
    galleryGrid.replaceChildren(
      ...galleryPhotos.map((p, i) => {
        const img = document.createElement("img");
        img.src = p.thumb_url;
        img.loading = "lazy";
        img.alt = "";
        img.addEventListener("click", () => openViewer(i));
        return img;
      }),
    );
  } catch (err) {
    console.error("gallery failed", err);
    galleryPhotos = [];
    galleryEl.classList.add("empty");
  }
}

// back from the viewer keeps the gallery's scroll position (no reload)
function backToGallery() {
  setState("gallery");
}

// ---------- viewer: full-size photo, swipe left/right ----------

const SWIPE_THRESHOLD = 80; // px the finger must travel to change photo
const TAP_SLOP = 10; // px of movement that still counts as a tap
const SLIDE_MS = 220;

function openViewer(index) {
  viewerIndex = index;
  setViewerImage(0);
  setState("viewer");
  updateViewer();
}

function setViewerImage(offsetPx, animate = false) {
  viewerImg.style.transition = animate ? `transform ${SLIDE_MS}ms ease-out` : "none";
  viewerImg.style.transform = `translateX(${offsetPx}px)`;
}

function updateViewer() {
  const photo = galleryPhotos[viewerIndex];
  viewerImg.src = photo.url;
  viewerCounter.textContent = `${viewerIndex + 1} / ${galleryPhotos.length}`;
  // preload neighbours so the next swipe is instant
  for (const i of [viewerIndex - 1, viewerIndex + 1]) {
    if (galleryPhotos[i]) new Image().src = galleryPhotos[i].url;
  }
  renderMenu(); // enable/disable ◀ ▶
}

// dir: +1 = next (older), -1 = previous (newer)
async function step(dir) {
  const target = viewerIndex + dir;
  if (target < 0 || target >= galleryPhotos.length || sliding) return;
  sliding = true;
  const width = viewerEl.clientWidth;
  setViewerImage(-dir * width, true); // slide current photo out
  await sleep(SLIDE_MS);
  viewerIndex = target;
  updateViewer();
  setViewerImage(dir * width); // new photo starts on the other side…
  void viewerImg.offsetWidth;
  setViewerImage(0, true); // …and slides in
  await sleep(SLIDE_MS);
  sliding = false;
}

let drag = null;

viewerEl.addEventListener("pointerdown", (e) => {
  if (sliding) return;
  drag = { id: e.pointerId, x: e.clientX, dx: 0 };
  viewerEl.setPointerCapture(e.pointerId);
});

viewerEl.addEventListener("pointermove", (e) => {
  if (!drag || e.pointerId !== drag.id) return;
  drag.dx = e.clientX - drag.x;
  const atEdge = (drag.dx > 0 && viewerIndex === 0) || (drag.dx < 0 && viewerIndex === galleryPhotos.length - 1);
  setViewerImage(atEdge ? drag.dx * 0.25 : drag.dx); // resist at the first/last photo
});

function endDrag(e) {
  if (!drag || e.pointerId !== drag.id) return;
  const { dx } = drag;
  drag = null;
  if (Math.abs(dx) < TAP_SLOP) {
    setViewerImage(0);
    backToGallery(); // a tap closes the viewer
  } else if (dx <= -SWIPE_THRESHOLD && viewerIndex < galleryPhotos.length - 1) {
    step(1);
  } else if (dx >= SWIPE_THRESHOLD && viewerIndex > 0) {
    step(-1);
  } else {
    setViewerImage(0, true); // not far enough: snap back
  }
}
viewerEl.addEventListener("pointerup", endDrag);
viewerEl.addEventListener("pointercancel", endDrag);

// arrow keys, handy when testing with a keyboard
document.addEventListener("keydown", (e) => {
  if (state !== "viewer") return;
  if (e.key === "ArrowRight") step(1);
  if (e.key === "ArrowLeft") step(-1);
  if (e.key === "Escape") backToGallery();
});

// ---------- toast ----------

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 4000);
}

// ---------- kiosk hardening ----------

// on the touchscreen (?kiosk=1) there is no mouse pointer
if (new URLSearchParams(location.search).has("kiosk")) document.documentElement.classList.add("kiosk");
document.addEventListener("contextmenu", (e) => e.preventDefault());
document.addEventListener("dragstart", (e) => e.preventDefault());

// ---------- start ----------

async function init() {
  try {
    const res = await fetch("/api/config");
    if (res.ok) config = { ...config, ...(await res.json()) };
  } catch { /* keep defaults */ }
  lang = loadLanguage(config.default_language);
  preview.classList.toggle("mirrored", !!config.mirror_preview);
  applyTexts();
  setState("live");
  startPreview();
}

init();
