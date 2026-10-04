"""Post-adhan dua catalog and helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import BASE_DIR

ARABIC = (
    "اللَّهُمَّ رَبَّ هَذِهِ الدَّعْوَةِ التَّامَّةِ "
    "وَالصَّلَاةِ الْقَائِمَةِ "
    "آتِ مُحَمَّدًا الْوَسِيلَةَ وَالْفَضِيلَةَ "
    "وَابْعَثْهُ مَقَامًا مَحْمُودًا الَّذِي وَعَدْتَهُ"
)

ARABIC_WITH_PROMISE = ARABIC + " إِنَّكَ لَا تُخْلِفُ الْمِيعَادَ"

TRANSLITERATION = (
    "Allāhumma rabba hādhihi-d-daʿwati-t-tāmmah, "
    "waṣ-ṣalāti-l-qāʾimah, "
    "āti Muḥammadan al-wasīlata wal-faḍīlah, "
    "wabʿath-hu maqāman maḥmūdan alladhī waʿadtah."
)

TRANSLITERATION_WITH_PROMISE = (
    TRANSLITERATION[:-1] + " Innaka lā tukhliful-mīʿād."
)

ENGLISH = (
    "O Allah, Lord of this perfect call and established prayer, "
    "grant Muhammad the means (al-wasilah) and virtue (al-fadilah), "
    "and raise him to the praised station You have promised him."
)

ENGLISH_WITH_PROMISE = ENGLISH + " Verily You never fail in Your promise."

DUA_CATALOG: list[dict[str, Any]] = [
    {
        "id": "short-authentic",
        "title": "Short authentic",
        "description": "Arabic only — Bukhari wording (Hisn al-Muslim). Best daily default.",
        "file": "audio/dua/short-authentic.mp3",
        "variant": "bukhari",
        "has_translation": False,
        "style": "normal",
        "arabic": ARABIC,
        "transliteration": TRANSLITERATION,
        "english": ENGLISH,
        "source": "Hisn al-Muslim / Bukhari 614",
    },
    {
        "id": "with-translation",
        "title": "With English translation",
        "description": "Arabic then English — helpful for kids and family learning.",
        "file": "audio/dua/with-translation.mp3",
        "variant": "bukhari",
        "has_translation": True,
        "style": "normal",
        "arabic": ARABIC,
        "transliteration": TRANSLITERATION,
        "english": ENGLISH,
        "source": "Bundled preview (Arabic + TTS English)",
    },
    {
        "id": "slow-teach",
        "title": "Slow / repeat-after-me",
        "description": "Paused phrases for teaching. Optional, not the daily default.",
        "file": "audio/dua/slow-teach.mp3",
        "variant": "bukhari",
        "has_translation": False,
        "style": "slow",
        "arabic": ARABIC,
        "transliteration": TRANSLITERATION,
        "english": ENGLISH,
        "source": "Bundled teaching preview",
    },
    {
        "id": "masjid-wording",
        "title": "Common masjid wording",
        "description": "Same dua including “innaka lā tukhliful-mīʿād” (common addition; scholars differ).",
        "file": "audio/dua/masjid-wording.mp3",
        "variant": "with_promise",
        "has_translation": False,
        "style": "normal",
        "arabic": ARABIC_WITH_PROMISE,
        "transliteration": TRANSLITERATION_WITH_PROMISE,
        "english": ENGLISH_WITH_PROMISE,
        "source": "Common masjid wording (labeled variant)",
    },
]


def list_duas() -> list[dict[str, Any]]:
    out = []
    for item in DUA_CATALOG:
        path = BASE_DIR / item["file"]
        entry = dict(item)
        entry["available"] = path.exists()
        # Browser preview path (served by /media/{path} and /media/audio mount)
        entry["url"] = f"/media/{item['file']}" if item["file"].startswith("audio/") else f"/media/audio/{item['file']}"
        out.append(entry)
    return out


def get_dua(dua_id: str) -> dict[str, Any] | None:
    for item in list_duas():
        if item["id"] == dua_id:
            return item
    return None


def resolve_dua_path(config: dict[str, Any]) -> Path | None:
    dua_id = config.get("dua_id")
    if dua_id:
        entry = get_dua(dua_id)
        if entry and entry["available"]:
            return BASE_DIR / entry["file"]
    audio_file = config.get("dua_audio_file")
    if audio_file:
        path = BASE_DIR / audio_file
        if path.exists():
            return path
    # Fallback to first available
    for item in list_duas():
        if item["available"]:
            return BASE_DIR / item["file"]
    return None
