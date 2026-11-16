// Photobox touch UI.
// States: live → countdown → (capture) → result → live
//         live → gallery → viewer → gallery → live
//         result / viewer → share (QR codes for phones) → back
//         live → wifi (hotspot QR code) → live
//         live → power1 → power2 → powering (two confirmations)

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
const shareEl = $("#share");
const wifiQr = $("#wifi-qr");
const wifiSsid = $("#wifi-ssid");
const photoQr = $("#photo-qr");
const shareTimerEl = $("#share-timer");
const powerTitle = $("#power-title");
const powerText = $("#power-text");

let config = {
  countdown_seconds: 3,
  mirror_preview: true,
  idle_timeout_seconds: 60,
  default_language: "en",
  hotspot: false,
  power_off: false,
};
let lang = "en";
let state = "live";
let idleTimer = null;
let toastTimer = null;
let galleryPhotos = [];
let viewerIndex = 0;
let sliding = false;
let lastPhoto = null; // the photo shown on the result screen
let shareReturn = "live"; // where "Back" goes from the QR codes
let shareTimer = null;
let sharing = false; // a share request is on its way

const t = (key) => TEXTS[lang][key] ?? key;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- menu ----------

// Taking a photo: tap the live preview (the hint says so), no extra button.
// Items with `when: false` are left out (e.g. no hotspot configured).
const liveMenu = (disabled) => [
  { key: "gallery", icon: "gallery", grow: true, action: openGallery, disabled },
  { key: "phone_wifi", icon: "wifi", action: openWifi, disabled, when: config.hotspot },
  { key: "language", icon: "language", small: true, action: toggleLanguage, disabled },
  { key: "power_off", icon: "power", small: true, action: () => setState("power1"), disabled, when: config.power_off },
];

const MENUS = {
  live: () => liveMenu(false),
  countdown: () => liveMenu(true),
  result: () => [
    { key: "again", icon: "again", primary: true, action: startCountdown },
    { key: "to_phone", icon: "phone", action: () => openShare(lastPhoto, "result"), when: config.hotspot },
    { key: "done", icon: "done", action: goLive },
  ],
  gallery: () => [{ key: "back", icon: "back", primary: true, action: goLive }],
  viewer: () => [
    { key: "previous", icon: "prev", grow: true, action: () => step(-1), disabled: viewerIndex <= 0 },
    { key: "next", icon: "next", grow: true, action: () => step(1), disabled: viewerIndex >= galleryPhotos.length - 1 },
    { key: "to_phone", icon: "phone", action: () => openShare(galleryPhotos[viewerIndex], "viewer"), when: config.hotspot },
    { key: "gallery", icon: "gallery", small: true, action: backToGallery },
  ],
  share: () => [{ key: "back", icon: "back", primary: true, action: closeShare }],
  wifi: () => [{ key: "back", icon: "back", primary: true, action: goLive }],
  // "Yes" sits at the bottom first and at the top second, so a double tap
  // on the same spot can't turn the box off by accident.
  power1: () => [
    { key: "cancel", icon: "back", primary: true, grow: true, action: goLive },
    { key: "power_confirm", icon: "power", danger: true, action: () => setState("power2") },
  ],
  power2: () => [
    { key: "power_confirm", icon: "power", danger: true, grow: true, action: powerOff },
    { key: "cancel", icon: "back", primary: true, action: goLive },
  ],
  powering: () => [],
};

function renderMenu() {
  menuButtons.replaceChildren(
    ...MENUS[state]().filter((item) => item.when !== false).map((item) => {
      const btn = document.createElement("button");
      btn.className =
        "menu-btn" +
        (item.primary ? " primary" : "") +
        (item.danger ? " danger" : "") +
        (item.small ? " small" : "") +
        (item.grow ? " grow" : "");
      btn.disabled = !!item.disabled;
      btn.innerHTML = `<svg aria-hidden="true"><use href="#icon-${item.icon}"></use></svg><span></span>`;
      btn.querySelector("span").textContent = t(item.key);
      if (item.action) btn.addEventListener("click", item.action);
      return btn;
    }),
  );
}

function setState(next) {
  if (state === "share" && next !== "share") stopShareTimer();
  if (next !== state) blockClicks(CLICK_GUARD_MS); // the screen changed under the finger
  state = next;
  app.dataset.state = next;
  if (next.startsWith("power")) renderPower();
  renderMenu();
  resetIdleTimer();
}

function applyTexts() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  if (state.startsWith("power")) renderPower();
  renderMenu();
}

function toggleLanguage() {
  lang = lang === "en" ? "de" : "en";
  saveLanguage(lang);
  applyTexts();
}

// ---------- double taps ----------

// The touch panel may report a tap twice (as touch and as mouse), and a tap
// that changes the screen must not also hit the button that appears under
// the finger. So clicks right after a click or a screen change are dropped.
const CLICK_GUARD_MS = 400;
let clicksBlockedUntil = 0;

function blockClicks(ms) {
  clicksBlockedUntil = Math.max(clicksBlockedUntil, performance.now() + ms);
}

document.addEventListener(
  "click",
  (e) => {
    if (performance.now() < clicksBlockedUntil) {
      e.stopImmediatePropagation();
      e.preventDefault();
      return;
    }
    blockClicks(CLICK_GUARD_MS);
  },
  true, // capture phase: before any button sees the click
);

// ---------- idle timeout ----------

function resetIdleTimer() {
  clearTimeout(idleTimer);
  if (["live", "countdown", "powering"].includes(state)) return;
  // the QR codes close after the idle time too; the link itself stays valid
  const onIdle = state === "share" ? closeShare : goLive;
  idleTimer = setTimeout(onIdle, config.idle_timeout_seconds * 1000);
}
document.addEventListener("pointerdown", resetIdleTimer, { passive: true });

// ---------- preview ----------

function startPreview() {
  preview.src = `/api/stream?t=${Date.now()}`;
}
preview.addEventListener("error", () => {
  if (state === "powering") return; // the backend is going away on purpose
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
    lastPhoto = photo;
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
  // ignore the doubled tap that just opened the viewer (see "double taps")
  if (sliding || performance.now() < clicksBlockedUntil) return;
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
    backToGallery(); // a tap closes the viewer (and blocks the click that follows)
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

// ---------- phones: hotspot + photo QR codes ----------

let wifiLoaded = false;

async function loadWifi() {
  if (wifiLoaded) return;
  const res = await fetch("/api/hotspot");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const body = await res.json();
  wifiQr.innerHTML = body.qr_svg; // SVG generated by our own backend
  wifiSsid.textContent = body.ssid;
  wifiLoaded = true;
}

async function openWifi() {
  try {
    await loadWifi();
  } catch (err) {
    console.error("hotspot failed", err);
    showToast(t("error_share"));
    return;
  }
  shareEl.dataset.mode = "wifi";
  setState("wifi");
}

async function openShare(photo, returnTo) {
  if (!photo || sharing || state === "share") return;
  sharing = true;
  let body;
  try {
    await loadWifi();
    const res = await fetch(`/api/share/${encodeURIComponent(photo.name)}`, { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    body = await res.json();
  } catch (err) {
    console.error("share failed", err);
    showToast(t("error_share"));
    return;
  } finally {
    sharing = false;
  }
  if (state !== returnTo) return; // the guest moved on while the code was loading
  photoQr.innerHTML = body.qr_svg;
  shareEl.dataset.mode = "photo";
  shareReturn = returnTo;
  setState("share");

  // Count down; when the link expires the codes are useless, so close them.
  // Closing earlier ("Back" or idle) keeps the link valid for the phone.
  const expiresAt = Date.now() + body.expires_in * 1000;
  const tick = () => {
    if (state !== "share") return stopShareTimer();
    const left = Math.max(0, Math.round((expiresAt - Date.now()) / 1000));
    shareTimerEl.textContent = `${t("share_valid")} ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
    if (left === 0) closeShare();
  };
  clearInterval(shareTimer);
  tick();
  shareTimer = setInterval(tick, 1000);
}

function stopShareTimer() {
  clearInterval(shareTimer);
  shareTimer = null;
  photoQr.replaceChildren();
}

function closeShare() {
  if (state === "share") setState(shareReturn);
}

// ---------- power off ----------

function renderPower() {
  const texts = {
    power1: ["power_q1", null],
    power2: ["power_q2", null],
    powering: ["power_bye", "power_bye_text"],
  }[state];
  powerTitle.textContent = t(texts[0]);
  powerText.textContent = texts[1] ? t(texts[1]) : "";
}

async function powerOff() {
  try {
    const res = await fetch("/api/power-off", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (err) {
    console.error("power off failed", err);
    showToast(t("error_power"));
    goLive();
    return;
  }
  preview.removeAttribute("src"); // stop the stream
  setState("powering");
}

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
