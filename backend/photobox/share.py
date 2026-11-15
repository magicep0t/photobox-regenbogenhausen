"""Sharing photos with guests' phones over the photobox hotspot.

The touchscreen shows two QR codes: one to join the hotspot Wi-Fi, one with a
short-lived link to a single photo. Links are random, belong to exactly one
photo and expire after a few minutes, so nothing piles up during a party.

Phones notice that the hotspot has no internet. Android then sends normal
browser traffic over mobile data, so a plain link to the Pi would not load.
The hotspot therefore acts as a *captive portal* (like hotel Wi-Fi): every
DNS name points to the Pi and the phones' connectivity checks get a redirect
to the portal page. Phones open that page in a sign-in window that always
uses the hotspot, and the page shows the photo currently offered on the
touchscreen. "Done" on that page marks the phone as signed in, so the
connectivity checks succeed and the phone stays connected (iPhones would
otherwise drop the network when the sign-in window is closed).
"""

from __future__ import annotations

import html
import secrets
import threading
import time

import segno
import segno.helpers


class ShareLinks:
    """In-memory map of random tokens to photo names, each with an expiry."""

    def __init__(self, ttl_seconds: float, clock=time.monotonic) -> None:
        self.ttl = ttl_seconds
        self._clock = clock
        self._links: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def create(self, name: str) -> str:
        token = secrets.token_urlsafe(12)  # 96 bits, not guessable
        with self._lock:
            self._purge()
            self._links[token] = (name, self._clock() + self.ttl)
        return token

    def resolve(self, token: str) -> str | None:
        """Photo name for a valid, unexpired token, else None."""
        with self._lock:
            self._purge()
            entry = self._links.get(token)
        return entry[0] if entry else None

    def latest(self) -> str | None:
        """Token of the newest unexpired link (the one on the touchscreen right now)."""
        with self._lock:
            self._purge()
            if not self._links:
                return None
            return max(self._links, key=lambda t: self._links[t][1])

    def __len__(self) -> int:
        with self._lock:
            self._purge()
            return len(self._links)

    def _purge(self) -> None:
        now = self._clock()
        for token in [t for t, (_, exp) in self._links.items() if exp <= now]:
            del self._links[token]


class SignedIn:
    """Phones (by IP in the hotspot) that tapped "Done" on the portal page."""

    def __init__(self, ttl_seconds: float = 3600, clock=time.monotonic) -> None:
        self.ttl = ttl_seconds
        self._clock = clock
        self._until: dict[str, float] = {}
        self._lock = threading.Lock()

    def add(self, ip: str) -> None:
        with self._lock:
            self._until[ip] = self._clock() + self.ttl

    def __contains__(self, ip: str) -> bool:
        with self._lock:
            now = self._clock()
            for key in [k for k, until in self._until.items() if until <= now]:
                del self._until[key]
            return ip in self._until


def qr_svg(data: str) -> str:
    """QR code as inline SVG that scales to its container (viewBox, no fixed size)."""
    return segno.make(data, error="m").svg_inline(scale=1, border=2, omitsize=True)


def wifi_qr_svg(ssid: str, password: str) -> str:
    qr = segno.helpers.make_wifi(ssid=ssid, password=password, security="WPA")
    return qr.svg_inline(scale=1, border=2, omitsize=True)


# ---------------------------------------------------------------- connectivity checks

# What phones and computers expect when the internet works. Before "Done"
# every check gets a redirect to the portal instead.
APPLE_SUCCESS = "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>"


def probe_success(path: str) -> tuple[int, str, str] | None:
    """(status, content type, body) for a known connectivity check, else None."""
    p = path.lower()
    if p.endswith(("generate_204", "gen_204")):  # Android, Chrome OS
        return 204, "text/plain", ""
    if p.endswith(("hotspot-detect.html", "success.html")) or p.startswith("/library/test/"):  # Apple
        return 200, "text/html", APPLE_SUCCESS
    if p == "/connecttest.txt":  # Windows 10+
        return 200, "text/plain", "Microsoft Connect Test"
    if p == "/ncsi.txt":  # older Windows
        return 200, "text/plain", "Microsoft NCSI"
    if p == "/success.txt":  # Firefox
        return 200, "text/plain", "success\n"
    return None


# ---------------------------------------------------------------- phone pages

TEXTS = {
    "en": {
        "title": "Your photo",
        "save": "Save photo",
        "hint": "Or press and hold the photo and choose “Save image” / “Save to Photos”.",
        "done": "Done",
        "done_hint": "iPhone: tap “Done”, then scan code ② with the camera to save the photo.",
        "expired_title": "Link expired",
        "expired": "This link is only valid for a few minutes. Tap “To phone” on the photobox again to get a new code.",
        "wait_title": "Connected to the photobox",
        "wait": "Tap “To phone” on your photo at the photobox. It will show up here.",
        "signed_in_title": "All set",
        "signed_in": "You can close this window now. Scan code ② on the photobox screen to open your photo.",
        "disconnect": "No internet in this Wi-Fi: disconnect from “{ssid}” when you're done.",
    },
    "de": {
        "title": "Dein Foto",
        "save": "Foto speichern",
        "hint": "Oder Foto lange drücken und „Bild speichern“ / „Zu Fotos hinzufügen“ wählen.",
        "done": "Fertig",
        "done_hint": "iPhone: „Fertig“ tippen, dann Code ② mit der Kamera scannen, um das Foto zu speichern.",
        "expired_title": "Link abgelaufen",
        "expired": "Dieser Link gilt nur ein paar Minuten. Tippe an der Photobox nochmal auf „Aufs Handy“, dann bekommst du einen neuen Code.",
        "wait_title": "Mit der Photobox verbunden",
        "wait": "Tippe an der Photobox bei deinem Foto auf „Aufs Handy“. Es erscheint dann hier.",
        "signed_in_title": "Alles klar",
        "signed_in": "Du kannst dieses Fenster jetzt schließen. Scanne Code ② auf dem Bildschirm der Photobox, um dein Foto zu öffnen.",
        "disconnect": "Dieses WLAN hat kein Internet: Trenne dich danach wieder von „{ssid}“.",
    },
}


def pick_language(accept_language: str | None) -> str:
    """'de' if the phone prefers German over English, else 'en'."""
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in TEXTS:
            return code
    return "en"


_STYLE = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: #0e0e10; color: #f5f5f7;
       font-family: system-ui, -apple-system, "Segoe UI", sans-serif; text-align: center; }
.rainbow { height: 8px; background: linear-gradient(90deg, #e40303, #ff8c00, #ffed00, #008026, #004dff, #750787); }
main { padding: 20px 16px 32px; max-width: 720px; margin: 0 auto; }
h1 { font-size: 26px; margin: 8px 0 18px; }
p { font-size: 18px; line-height: 1.45; color: #d4d4d8; }
img { display: block; width: 100%; border-radius: 12px; background: #18181c; }
.btn { display: block; width: 100%; margin: 20px 0 12px; padding: 18px; border: 0; border-radius: 14px;
       background: #ffd60a; color: #111; font: inherit; font-size: 21px; font-weight: 700; text-decoration: none; }
.btn.secondary { background: #24242a; color: #f5f5f7; }
.hint { font-size: 15px; color: #a1a1aa; }
"""


def _page(lang: str, title: str, body: str, refresh: int | None = None) -> str:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        f"{meta}<title>{html.escape(title)}</title><style>{_STYLE}</style></head>"
        f'<body><div class="rainbow"></div><main>{body}</main></body></html>'
    )


def _done_form(t: dict) -> str:
    return (
        '<form method="post" action="/signin">'
        f'<button class="btn secondary" type="submit">{html.escape(t["done"])}</button></form>'
        f'<p class="hint">{html.escape(t["done_hint"])}</p>'
    )


def photo_page(lang: str, token: str, filename: str, portal: bool = False) -> str:
    """The shared photo with a save button. On the portal also a "Done" button."""
    t = TEXTS[lang]
    src = f"/d/{token}/photo.jpg"
    body = (
        f"<h1>{html.escape(t['title'])}</h1>"
        f'<img src="{src}" alt="">'
        f'<a class="btn" download="{html.escape(filename)}" href="{src}?download=1">{html.escape(t["save"])}</a>'
        f'<p class="hint">{html.escape(t["hint"])}</p>'
        + (_done_form(t) if portal else "")
    )
    return _page(lang, t["title"], body)


def waiting_page(lang: str) -> str:
    """Portal page while no photo is offered; reloads until one is."""
    t = TEXTS[lang]
    body = f"<h1>{html.escape(t['wait_title'])}</h1><p>{html.escape(t['wait'])}</p>" + _done_form(t)
    return _page(lang, t["wait_title"], body, refresh=3)


def signed_in_page(lang: str, ssid: str) -> str:
    t = TEXTS[lang]
    body = (
        f"<h1>{html.escape(t['signed_in_title'])}</h1><p>{html.escape(t['signed_in'])}</p>"
        f'<p class="hint">{html.escape(t["disconnect"].format(ssid=ssid))}</p>'
    )
    return _page(lang, t["signed_in_title"], body)


def expired_page(lang: str) -> str:
    t = TEXTS[lang]
    return _page(lang, t["expired_title"], f"<h1>{html.escape(t['expired_title'])}</h1><p>{html.escape(t['expired'])}</p>")
