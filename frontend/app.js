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
const viewerImg = $("#viewer-img");
const toast = $("#toast");
const menuButtons = $("#menu-buttons");

let config = { countdown_seconds: 3, mirror_preview: true, idle_timeout_seconds: 60, default_language: "en" };
let lang = "en";
let state = "live";
let idleTimer = null;
let toastTimer = null;

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
  viewer: [{ key: "back", icon: "back", primary: true, action: openGallery }],
};

function renderMenu() {
  menuButtons.replaceChildren(
    ...MENUS[state].map((item) => {
      const btn = document.createElement("button");
      btn.className = "menu-btn" + (item.primary ? " primary" : "") + (item.small ? " small" : "");
      btn.disabled = !!item.disabled;
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
  try {
    const res = await fetch("/api/photos?limit=60");
    const photos = await res.json();
    galleryEl.classList.toggle("empty", photos.length === 0);
    galleryGrid.replaceChildren(
      ...photos.map((p) => {
        const img = document.createElement("img");
        img.src = p.thumb_url;
        img.loading = "lazy";
        img.alt = "";
        img.addEventListener("click", () => openViewer(p));
        return img;
      }),
    );
  } catch (err) {
    console.error("gallery failed", err);
    galleryEl.classList.add("empty");
  }
}

function openViewer(photo) {
  viewerImg.src = photo.url;
  setState("viewer");
}
viewerImg.addEventListener("click", openGallery);

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
