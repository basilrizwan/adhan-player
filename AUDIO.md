# Audio attribution

Bundled media is for personal / da‘wah use with the Adhan Player. Replace any file under `audio/` with your own recordings if you need different licensing for redistribution.

## Adhan

- Default install may download a Mishary Rashid Alafasy adhan from the Internet Archive (`AdhanMisharyRashid`).
- Your device may already contain custom files (`audio/adhan.mp3`, `audio/fajr.mp3`) or samples under `audio/candidates/`.

## Surah Kahf

- `audio/kahf.mp3` — user-provided / local copy used by the Thursday Maghrib feature.

## Post-adhan dua (`audio/dua/`)

| File | Notes |
| --- | --- |
| `SOURCE-hisn-al-muslim-adhan.mp3` | Hisn al-Muslim — Adhan chapter audio (Qahtani), used as the Arabic source for previews |
| `from-fajr.mp3` | Dua clipped from `fajr.mp3` at 3:08 (15s) — current default |
| `with-translation.mp3` | Arabic + English TTS translation (macOS `say` / Samantha) for family learning |
| `slow-teach.mp3` | Slowed full chapter for teaching |
| `masjid-wording.mp3` | Arabic preview + English “innaka lā tukhliful-mīʿād” label (scholars differ on this addition) |

If you redistribute this project, verify the license terms of each recording you keep, or ship the repo **without** binary audio and document download steps in the README.

## Browser vs speaker preview

- Browser: `/media/audio/...`
- Device speaker: `POST /api/play`
