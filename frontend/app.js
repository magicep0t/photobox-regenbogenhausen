// Photobox touch UI.
// States: live → countdown → (capture) → result → live
//         live → gallery → viewer → gallery → live
//         result / viewer → share (QR codes for phones) → back
//         live → wifi (hotspot QR code) → live
//         live → settings (status over the preview) → live
//         settings → confirm → settings      (network mode, SSH, restart)
//         settings → power1 → power2 → powering (two confirmations)
//         settings → confirm → rebooting

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
const powerIcon = $("#power-icon");
const statsEl = $("#stats");

let config = {
  countdown_seconds: 3,
  mirror_preview: true,
  idle_timeout_seconds: 60,
  default_language: "en",
  hotspot: false,
  power_off: false,
  reboot: false,
  network_mode: false,
  ssh_password: false,
  camera: true,
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
let status = null; // last /api/status, shown on the settings screen
let statusTimer = null;
let confirmation = null; // the question on the confirm screen

const t = (key) => TEXTS[lang][key] ?? key;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- menu ----------

// Taking a photo: tap the live preview (the hint says so), no extra button.
// Items with `when: false` are left out (e.g. no hotspot configured).
const liveMenu = (disabled) => [
  { key: "gallery", icon: "gallery", grow: true, action: openGallery, disabled },
  { key: "phone_wifi", icon: "wifi", action: openWifi, disabled, when: config.hotspot },
  { key: "language", icon: "language", small: true, action: toggleLanguage, disabled },
  { key: "settings", icon: "settings", small: true, action: openSettings, disabled },
];

// The buttons show what they will do; they are off until the status is known.
function settingsMenu() {
  const mode = status?.mode;
  const password = status?.ssh?.password;
  return [
    { key: "back", icon: "back", primary: true, action: goLive },
    {
      key: mode === "standalone" ? "to_home" : "to_standalone",
      icon: "wifi",
      compact: true,
      disabled: !mode,
      action: () => askNetworkMode(mode === "standalone" ? "home" : "standalone"),
      when: config.network_mode,
    },
    {
      key: password ? "ssh_pw_block" : "ssh_pw_allow",
      icon: "key",
      compact: true,
      warn: !!password,
      disabled: password === undefined,
      action: () => askSshPassword(!password),
      when: config.ssh_password,
    },
    { key: "reboot", icon: "restart", compact: true, action: askReboot, when: config.reboot },
    { key: "power_off", icon: "power", compact: true, action: () => setState("power1"), when: config.power_off },
  ];
}

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
  settings: settingsMenu,
  confirm: () => [
    { key: "cancel", icon: "back", primary: true, grow: true, action: openSettings },
    { key: confirmation.yes, icon: confirmation.icon, danger: confirmation.danger, action: confirmYes },
  ],
  // "Yes" sits at the bottom first and at the top second, so a double tap
  // on the same spot can't turn the box off by accident.
  power1: () => [
    { key: "cancel", icon: "back", primary: true, grow: true, action: openSettings },
    { key: "power_confirm", icon: "power", danger: true, action: () => setState("power2") },
  ],
  power2: () => [
    { key: "power_confirm", icon: "power", danger: true, grow: true, action: powerOff },
    { key: "cancel", icon: "back", primary: true, action: openSettings },
  ],
  powering: () => [],
  rebooting: () => [],
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
        (item.compact ? " compact" : "") +
        (item.warn ? " warn" : "") +
        (item.grow ? " grow" : "");
      btn.disabled = !!item.disabled;
      btn.innerHTML = `<svg aria-hidden="true"><use href="#icon-${item.icon}"></use></svg><span></span>`;
      btn.querySelector("span").textContent = t(item.key);
      if (item.action) btn.addEventListener("click", item.action);
      return btn;
    }),
  );
}

// states that show the question/goodbye box
const BOX_STATES = ["power1", "power2", "powering", "confirm", "rebooting"];
// states during which the status keeps updating
const STATUS_STATES = ["settings", "confirm", "power1", "power2"];

function setState(next) {
  if (state === "share" && next !== "share") stopShareTimer();
  if (next !== state) blockClicks(CLICK_GUARD_MS); // the screen changed under the finger
  state = next;
  app.dataset.state = next;
  if (BOX_STATES.includes(next)) renderBox();
  if (!STATUS_STATES.includes(next)) stopStatus();
  renderMenu();
  resetIdleTimer();
}

function applyTexts() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  if (BOX_STATES.includes(state)) renderBox();
  if (status) renderStatus();
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
  if (["live", "countdown", "powering", "rebooting"].includes(state)) return;
  // the QR codes close after the idle time too; the link itself stays valid
  const onIdle = state === "share" ? closeShare : goLive;
  // the status screen is for watching, so it stays longer
  const factor = STATUS_STATES.includes(state) ? 5 : 1;
  idleTimer = setTimeout(onIdle, config.idle_timeout_seconds * 1000 * factor);
}
document.addEventListener("pointerdown", resetIdleTimer, { passive: true });

// ---------- preview ----------

function startPreview() {
  preview.src = `/api/stream?t=${Date.now()}`;
}
preview.addEventListener("error", () => {
  if (state === "powering" || state === "rebooting") return; // the backend is going away on purpose
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
    if (res.status === 503) {
      showToast(t("error_capture_camera"));
      setState("live");
      return;
    }
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

// ---------- settings: status, network mode, SSH, restart ----------

function openSettings() {
  setState("settings");
  if (status) renderStatus();
  refreshStatus();
  clearInterval(statusTimer);
  statusTimer = setInterval(refreshStatus, 3000);
}

function stopStatus() {
  clearInterval(statusTimer);
  statusTimer = null;
}

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    status = await res.json();
  } catch (err) {
    console.error("status failed", err);
    return;
  }
  if (!STATUS_STATES.includes(state)) return;
  renderStatus();
  if (state === "settings") renderMenu(); // button labels depend on the status
}

const fmt = (key, values) => t(key).replace(/\{(\w+)\}/g, (_, k) => values[k] ?? "");

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

// one "label: value" line; value is text or an element
function row(label, value, cls) {
  const r = el("div", "st-row");
  const v = el("span", cls);
  if (value instanceof Node) v.append(value);
  else v.textContent = value ?? "–";
  r.append(el("span", null, label), v);
  return r;
}

function card(titleKey, ...children) {
  const c = el("section", "st-card");
  c.append(el("h3", null, t(titleKey)), ...children);
  return c;
}

function duration(seconds) {
  if (seconds == null) return "–";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
}

function renderStatus() {
  const s = status;
  const net = (id) => s.networks.find((n) => n.id === id);
  const ips = (n) => (n.ipv4.length ? n.ipv4.map((a) => a.split("/")[0]).join(", ") : null);

  // network
  const netCard = card("st_network");
  netCard.append(row(t("st_mode"), el("span", "st-badge", t(s.mode === "standalone" ? "mode_standalone" : "mode_home"))));
  const wifi = net("wifi");
  if (wifi) {
    const label = wifi.ap ? t("st_admin_wifi") : t("st_wifi");
    const what = wifi.ap ? wifi.ssid ?? s.admin_wifi?.ssid : wifi.ssid ? wifi.ssid : t("st_not_connected");
    netCard.append(row(label, [what, ips(wifi)].filter(Boolean).join(" · "), wifi.ssid || wifi.ap ? null : "st-warn"));
    netCard.append(row("", dhcpText(wifi), "st-sub"));
  }
  const cable = net("cable");
  if (cable) {
    netCard.append(row(t("st_cable"), ips(cable) ?? t("st_not_connected"), ips(cable) ? null : "st-sub"));
  }
  const guest = net("guest");
  if (guest) {
    if (!guest.present) netCard.append(row(t("st_guest"), t("st_no_stick"), "st-warn"));
    else {
      netCard.append(row(t("st_guest"), [guest.ssid ?? t("st_off"), ips(guest)].filter(Boolean).join(" · ")));
      netCard.append(row("", dhcpText(guest), "st-sub"));
    }
  }
  if (s.admin_wifi) {
    const box = el("div", "st-admin");
    const qr = el("div", "qr");
    qr.innerHTML = s.admin_wifi.qr_svg; // SVG generated by our own backend
    box.append(qr, el("div", "st-sub", fmt("st_admin_hint", { ip: s.admin_wifi.address, ssid: s.admin_wifi.ssid })));
    netCard.append(box);
  }

  // connected devices (on the Pi's own access points)
  const devCard = card("st_devices");
  const aps = s.networks.filter((n) => n.present && n.ap);
  for (const n of aps) {
    devCard.append(el("div", "st-sub", `${n.id === "guest" ? t("st_guest") : t("st_admin_wifi")} (${n.clients.length})`));
    for (const c of n.clients) {
      const d = el("div", "st-device");
      d.append(
        el("div", null, [c.name, c.ip].filter(Boolean).join(" · ") || c.mac),
        el("div", "st-sub", [c.mac, c.signal != null ? `${c.signal} dBm` : null, duration(c.connected_s)].filter(Boolean).join(" · ")),
      );
      devCard.append(d);
    }
  }
  if (!aps.length) devCard.append(el("div", "st-sub", t("st_none")));

  // ssh
  const ssh = s.ssh;
  const sshCard = card(
    "st_ssh",
    row(t("st_service"), t(ssh.active ? "st_running" : "st_stopped"), ssh.active ? "st-good" : "st-warn"),
    row(t("st_login"), t(ssh.password ? "st_password_on" : "st_keys_only"), ssh.password ? "st-bad" : "st-good"),
    row(t("st_sessions"), ssh.sessions.length ? `${ssh.sessions.length}: ${ssh.sessions.join(", ")}` : t("st_none")),
  );

  // system
  const y = s.system;
  const temp = y.temp_c;
  const now = y.throttled.filter((f) => !f.endsWith("_past"));
  const past = y.throttled.filter((f) => f.endsWith("_past")).map((f) => t(`th_${f.replace("_past", "")}`));
  const throttleText = now.length
    ? now.map((f) => t(`th_${f}`)).join(", ")
    : past.length ? fmt("st_throttle_past", { list: past.join(", ") }) : t("st_throttle_none");
  const time = new Date(y.time);
  const sysCard = card(
    "st_system",
    row(t("st_cpu_temp"), temp == null ? null : `${temp.toFixed(1)} °C`, temp == null ? null : temp >= 80 ? "st-bad" : temp >= 70 ? "st-warn" : "st-good"),
    row(t("st_throttling"), throttleText, now.length ? "st-bad" : past.length ? "st-warn" : "st-good"),
    row(t("st_load"), `${y.load[0]} / ${y.cpus}`),
    row(t("st_memory"), y.mem_total_mb ? `${y.mem_used_mb} / ${y.mem_total_mb} MB` : null),
    row(t("st_disk"), y.disk_free_gb != null ? `${y.disk_free_gb} / ${y.disk_total_gb} GB` : null),
    row(t("st_photos"), String(y.photos)),
    row(t("st_camera"), y.camera === "unavailable" ? t("st_camera_missing") : y.camera.replace(/^picamera2 \((.*)\)$/, "$1"), y.camera === "unavailable" ? "st-bad" : null),
    row(
      t("st_time"),
      `${time.toLocaleString(lang === "de" ? "de-DE" : "en-GB", { dateStyle: "short", timeStyle: "short" })} · ${t(y.ntp ? "st_ntp_ok" : "st_ntp_no")}`,
      y.ntp === false ? "st-warn" : null,
    ),
    row(t("st_uptime"), duration(y.uptime_s)),
    row(t("st_build"), y.build),
  );

  const left = el("div");
  left.style.display = "grid";
  left.style.gap = "20px";
  left.append(netCard, devCard);
  const right = el("div");
  right.style.display = "grid";
  right.style.gap = "20px";
  right.style.alignContent = "start";
  right.append(sshCard, sysCard);
  statsEl.replaceChildren(left, right);
}

function dhcpText(n) {
  if (n.dhcp === "server") return fmt("st_dhcp_server", { n: n.dhcp_leases ?? 0, pool: n.dhcp_pool ?? "?" });
  if (n.dhcp === "client") return t("st_dhcp_client");
  return "";
}

// ---------- questions ----------

function ask(question) {
  confirmation = question;
  setState("confirm");
}

async function confirmYes() {
  const question = confirmation;
  try {
    await question.run();
  } catch (err) {
    console.error("settings action failed", err);
    showToast(t("error_settings"));
    openSettings();
    return;
  }
  if (question.after) question.after();
  else openSettings();
}

async function post(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

function askNetworkMode(mode) {
  const standalone = mode === "standalone";
  ask({
    title: standalone ? "q_standalone" : "q_home",
    text: standalone ? "q_standalone_text" : "q_home_text",
    values: { ssid: status?.admin_wifi?.ssid ?? "Photobox-Admin", ip: "192.168.73.1" },
    icon: "wifi",
    yes: "switch_confirm",
    run: async () => {
      await post("/api/network-mode", { mode });
      showToast(t("switching"), "info");
    },
  });
}

function askSshPassword(enabled) {
  ask({
    title: enabled ? "q_ssh_on" : "q_ssh_off",
    text: enabled ? "q_ssh_on_text" : "q_ssh_off_text",
    icon: "key",
    yes: "yes",
    danger: enabled,
    run: () => post("/api/ssh-password", { enabled }),
  });
}

function askReboot() {
  ask({
    title: "q_reboot",
    text: "q_reboot_text",
    icon: "restart",
    yes: "reboot_confirm",
    danger: true,
    run: () => post("/api/reboot"),
    after: () => {
      preview.removeAttribute("src"); // stop the stream
      setState("rebooting");
      waitForRestart();
    },
  });
}

// after a restart the kiosk browser is started anew; this only helps when
// the page is open somewhere else (e.g. a laptop during development)
async function waitForRestart() {
  await sleep(20000);
  while (state === "rebooting") {
    try {
      if ((await fetch("/api/health", { cache: "no-store" })).ok) return location.reload();
    } catch { /* still down */ }
    await sleep(3000);
  }
}

// ---------- question / goodbye box ----------

function renderBox() {
  if (state === "confirm") {
    powerIcon.setAttribute("href", `#icon-${confirmation.icon}`);
    powerTitle.textContent = fmt(confirmation.title, confirmation.values ?? {});
    powerText.textContent = fmt(confirmation.text, confirmation.values ?? {});
    return;
  }
  const [icon, title, text] = {
    power1: ["power", "power_q1", null],
    power2: ["power", "power_q2", null],
    powering: ["power", "power_bye", "power_bye_text"],
    rebooting: ["restart", "rebooting", "rebooting_text"],
  }[state];
  powerIcon.setAttribute("href", `#icon-${icon}`);
  powerTitle.textContent = t(title);
  powerText.textContent = text ? t(text) : "";
}

// ---------- power off ----------

async function powerOff() {
  try {
    const res = await fetch("/api/power-off", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (err) {
    console.error("power off failed", err);
    showToast(t("error_power"));
    openSettings();
    return;
  }
  preview.removeAttribute("src"); // stop the stream
  setState("powering");
}

// ---------- toast ----------

function showToast(message, kind = "error") {
  toast.textContent = message;
  toast.classList.toggle("info", kind === "info");
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
  // without a camera the preview shows a notice, which must stay readable
  preview.classList.toggle("mirrored", !!config.mirror_preview && config.camera);
  app.classList.toggle("no-camera", !config.camera);
  applyTexts();
  setState("live");
  startPreview();
}

init();
