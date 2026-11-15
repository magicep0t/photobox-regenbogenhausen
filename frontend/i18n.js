// UI texts. English is the default; German via the language button.

export const TEXTS = {
  en: {
    tap_to_start: "Tap to take a photo",
    gallery: "Gallery",
    language: "Deutsch",
    again: "Again",
    done: "Done",
    back: "Back",
    previous: "Previous",
    next: "Next",
    smile: "Smile!",
    empty_gallery: "No photos yet",
    error_capture: "Oops, that didn't work. Please try again.",
    error_preview: "Camera not available",
    to_phone: "To phone",
    phone_wifi: "Phone Wi-Fi",
    share_step_wifi: "Join the Wi-Fi",
    share_step_photo: "Open your photo",
    wifi_name: "Wi-Fi:",
    share_valid: "Code valid for",
    share_next: "Then tap “To phone” on your photo.",
    share_hint: "After connecting, your photo usually opens by itself. If not, scan code ②.",
    error_share: "Could not create the code. Please try again.",
    power_off: "Turn off",
    power_confirm: "Yes, turn off",
    cancel: "Cancel",
    power_q1: "Turn off the photobox?",
    power_q2: "Really turn off the photobox?!",
    power_bye: "The photobox is shutting down…",
    power_bye_text: "Please wait about 20 seconds before unplugging it.",
    error_power: "Could not turn off. Please try again.",
  },
  de: {
    tap_to_start: "Tippen für ein Foto",
    gallery: "Galerie",
    language: "English",
    again: "Nochmal",
    done: "Fertig",
    back: "Zurück",
    previous: "Vorheriges",
    next: "Nächstes",
    smile: "Lächeln!",
    empty_gallery: "Noch keine Fotos",
    error_capture: "Das hat nicht geklappt. Bitte nochmal versuchen.",
    error_preview: "Kamera nicht verfügbar",
    to_phone: "Aufs Handy",
    phone_wifi: "Handy-WLAN",
    share_step_wifi: "Mit dem WLAN verbinden",
    share_step_photo: "Foto öffnen",
    wifi_name: "WLAN:",
    share_valid: "Code gültig noch",
    share_next: "Danach bei deinem Foto auf „Aufs Handy“ tippen.",
    share_hint: "Nach dem Verbinden öffnet sich dein Foto meist von selbst. Sonst Code ② scannen.",
    error_share: "Code konnte nicht erstellt werden. Bitte nochmal versuchen.",
    power_off: "Ausschalten",
    power_confirm: "Ja, ausschalten",
    cancel: "Abbrechen",
    power_q1: "Photobox ausschalten?",
    power_q2: "Photobox wirklich ausschalten?!",
    power_bye: "Die Photobox wird ausgeschaltet…",
    power_bye_text: "Bitte etwa 20 Sekunden warten, bevor du den Stecker ziehst.",
    error_power: "Ausschalten hat nicht geklappt. Bitte nochmal versuchen.",
  },
};

const STORAGE_KEY = "photobox.lang";

export function loadLanguage(fallback) {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved in TEXTS) return saved;
  } catch { /* storage unavailable: use fallback */ }
  return fallback in TEXTS ? fallback : "en";
}

export function saveLanguage(lang) {
  try { localStorage.setItem(STORAGE_KEY, lang); } catch { /* ignore */ }
}
