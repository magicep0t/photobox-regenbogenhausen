"""Sharing photos with guests' phones over the photobox hotspot.

The touchscreen shows two QR codes: one to join the hotspot Wi-Fi, one with a
short-lived link to a single photo. Links are random, belong to exactly one
photo and expire after a few minutes, so nothing piles up during a party.
"""

from __future__ import annotations

import html
import json
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

    def __len__(self) -> int:
        with self._lock:
            self._purge()
            return len(self._links)

    def _purge(self) -> None:
        now = self._clock()
        for token in [t for t, (_, exp) in self._links.items() if exp <= now]:
            del self._links[token]


def qr_svg(data: str) -> str:
    """QR code as inline SVG that scales to its container (viewBox, no fixed size)."""
    return segno.make(data, error="m").svg_inline(scale=1, border=2, omitsize=True)


def wifi_qr_svg(ssid: str, password: str) -> str:
    qr = segno.helpers.make_wifi(ssid=ssid, password=password, security="WPA")
    return qr.svg_inline(scale=1, border=2, omitsize=True)


# ---------------------------------------------------------------- phone pages

TEXTS = {
    "en": {
        "title": "Your photo",
        "save": "Save photo",
        "loading": "Loading photo…",
        "ios_hint": "iPhone: press and hold the photo, then “Save to Photos”.",
        "expired_title": "Link expired",
        "expired": "This link is only valid for a few minutes. Tap “To phone” on the photobox again to get a new code.",
        "index_title": "Photobox",
        "index": "You're connected. Now scan the photo code on the photobox screen.",
        "failed": "Loading failed. Tap “To phone” on the photobox again.",
    },
    "de": {
        "title": "Dein Foto",
        "save": "Foto speichern",
        "loading": "Foto wird geladen…",
        "ios_hint": "iPhone: Foto lange drücken, dann „Zu Fotos hinzufügen“.",
        "expired_title": "Link abgelaufen",
        "expired": "Dieser Link gilt nur ein paar Minuten. Tippe an der Photobox nochmal auf „Aufs Handy“, dann bekommst du einen neuen Code.",
        "index_title": "Photobox",
        "index": "Du bist verbunden. Scanne jetzt den Foto-Code auf dem Bildschirm der Photobox.",
        "failed": "Laden fehlgeschlagen. Tippe an der Photobox nochmal auf „Aufs Handy“.",
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
img:not([src]) { min-height: 40vh; }
.btn { display: block; margin: 20px 0 12px; padding: 18px; border-radius: 14px; background: #ffd60a;
       color: #111; font-size: 21px; font-weight: 700; text-decoration: none; }
.btn[aria-disabled="true"] { opacity: .4; pointer-events: none; }
.hint { font-size: 15px; color: #a1a1aa; }
"""


def _page(lang: str, title: str, body: str) -> str:
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head>"
        f'<body><div class="rainbow"></div><main>{body}</main></body></html>'
    )


def photo_page(lang: str, token: str, filename: str) -> str:
    t = TEXTS[lang]
    src = f"/d/{token}/photo.jpg"
    # The photo is fetched once into memory right away (the link expires soon),
    # then shown and offered for download from that copy.
    script = f"""
<script>
(async () => {{
  const img = document.getElementById("photo");
  const btn = document.getElementById("save");
  try {{
    const res = await fetch({json.dumps(src)});
    if (!res.ok) throw new Error(res.status);
    const url = URL.createObjectURL(await res.blob());
    img.src = url;
    btn.href = url;
    btn.setAttribute("aria-disabled", "false");
    document.getElementById("status").remove();
  }} catch (e) {{
    document.getElementById("status").textContent = {json.dumps(t["failed"])};
  }}
}})();
</script>"""
    body = (
        f"<h1>{html.escape(t['title'])}</h1>"
        f'<p id="status">{html.escape(t["loading"])}</p>'
        '<img id="photo" alt="">'
        f'<a id="save" class="btn" aria-disabled="true" download="{html.escape(filename)}" '
        f'href="{src}?download=1">{html.escape(t["save"])}</a>'
        f'<p class="hint">{html.escape(t["ios_hint"])}</p>'
        + script
    )
    return _page(lang, t["title"], body)


def expired_page(lang: str) -> str:
    t = TEXTS[lang]
    return _page(lang, t["expired_title"], f"<h1>{html.escape(t['expired_title'])}</h1><p>{html.escape(t['expired'])}</p>")


def index_page(lang: str) -> str:
    t = TEXTS[lang]
    return _page(lang, t["index_title"], f"<h1>{html.escape(t['index_title'])}</h1><p>{html.escape(t['index'])}</p>")
