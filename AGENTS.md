# Agent instructions — Adhan Player

You are helping a user configure a **local Adhan Player** on their network.
The device is a Raspberry Pi (or compatible) running a FastAPI app on port **8080**.

## Goals

- Prefer HTTP APIs over SSH.
- Never invent cloud accounts; this product is local-first.
- Keep `sleep_enabled` false unless the user explicitly wants power saving and understands the UI will go offline.

## Discover the device

1. Try `http://adhan.local:8080/api/health`
2. Or scan mDNS for `_adhan._tcp`
3. Or ask the user for the IP shown on first-run / QR in the web UI

## Typical setup flow

1. `GET /api/status` — check `setup_complete`, clock health, URLs
2. `GET /api/duas` — list post-adhan dua options
3. `POST /api/play` with `{"kind":"dua","dua_id":"..."}` so the user can hear options on the speaker
4. `PATCH /api/config` with location, method, volumes, selected `dua_id`, `setup_complete: true`
5. `GET /api/schedule` — confirm today’s times look right
6. Optional: `POST /api/play` `{"kind":"test"}` for a full adhan+dua test

## Config fields that matter

| Field | Meaning |
| --- | --- |
| `latitude`, `longitude`, `timezone` | Location |
| `location_name` | Display name |
| `method` | Calculation method (2 = ISNA) |
| `school` | 0 standard Asr, 1 Hanafi |
| `volume`, `fajr_volume` | 0–100 |
| `dua_enabled`, `dua_id` | Post-adhan dua |
| `enabled_prayers` | Subset of Fajr/Dhuhr/Asr/Maghrib/Isha |
| `audio_output` | auto / hdmi / headphone |
| `sleep_enabled` | Advanced; disables portal while asleep |
| `kahf_enabled` | Thursday Surah Kahf after Maghrib |

## Safety

- Only play files under `audio/`
- Do not disable Avahi / mDNS
- If `clock_ok` is false, tell the user to fix NTP before trusting prayer times

Full OpenAPI: `/docs` · Machine summary: `/llms.txt` · Skill: `/docs/skill.md`
