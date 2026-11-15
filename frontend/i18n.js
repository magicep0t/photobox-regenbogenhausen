// UI texts. English is the default; German via the language button.

export const TEXTS = {
  en: {
    tap_to_start: "Tap to take a photo",
    take_photo: "Take photo",
    gallery: "Gallery",
    language: "Deutsch",
    again: "Again",
    done: "Done",
    back: "Back",
    smile: "Smile!",
    empty_gallery: "No photos yet",
    error_capture: "Oops, that didn't work. Please try again.",
    error_preview: "Camera not available",
  },
  de: {
    tap_to_start: "Tippen für ein Foto",
    take_photo: "Foto machen",
    gallery: "Galerie",
    language: "English",
    again: "Nochmal",
    done: "Fertig",
    back: "Zurück",
    smile: "Lächeln!",
    empty_gallery: "Noch keine Fotos",
    error_capture: "Das hat nicht geklappt. Bitte nochmal versuchen.",
    error_preview: "Kamera nicht verfügbar",
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
