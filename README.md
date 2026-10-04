# Adhan Player

Local-first Raspberry Pi speaker that plays the adhan at prayer times — with a phone-friendly setup portal, post-adhan dua previews, and HTTP APIs so any AI agent on your LAN can configure it.

No cloud account. Each home runs its own device.

## Features

- Offline prayer times (`adhanpy`) with optional Aladhan refresh
- Web portal at `http://adhan.local:8080` (PWA)
- Post-adhan dua catalog with browser + speaker preview
- Mute / skip / test play / night (Fajr) volume
- mDNS discovery (`_adhan._tcp`)
- Optional Wi‑Fi setup hotspot helper
- Agent docs: [`llms.txt`](llms.txt), [`AGENTS.md`](AGENTS.md), [`docs/skill.md`](docs/skill.md), OpenAPI `/docs`
- Thin Expo companion app under [`mobile/AdhanCompanion`](mobile/AdhanCompanion)

## Quick start (Raspberry Pi)

### A. Flash + auto-install (recommended)

1. Flash **Raspberry Pi OS Lite (64-bit)** with [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. In Imager: set Wi‑Fi, enable SSH, choose username/password
3. On your Mac, with the SD card still mounted:

```bash
./prepare-sd.sh
```

4. Boot the Pi with a speaker attached  
5. After ~3–5 minutes on the second boot, open **http://adhan.local:8080**

### B. Manual install over SSH

```bash
git clone https://github.com/<you>/adhan-player.git
cd adhan-player
./setup.sh
```

Then open `http://adhan.local:8080` and complete Setup.

### No Wi‑Fi yet?

```bash
sudo ./scripts/hotspot-setup.sh
```

Join `Adhan-XXXX` / `adhan-setup`, then open the portal IP shown (often `http://10.42.0.1:8080`).

## Local development (Mac)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

Open http://127.0.0.1:8080

Test adhan+dua once:

```bash
python adhan_player.py --test
```

## Configure with an AI agent

Point any local agent at:

- http://adhan.local:8080/llms.txt
- http://adhan.local:8080/AGENTS.md
- http://adhan.local:8080/openapi.json

Example:

```bash
curl -s http://adhan.local:8080/api/config -X PATCH \
  -H 'Content-Type: application/json' \
  -d '{"setup_complete":true,"latitude":30.27,"longitude":-97.74,"timezone":"America/Chicago","dua_id":"short-authentic"}'
```

## Important defaults

- **`sleep_enabled: false`** so the portal stays online (hardware sleep makes the UI unreachable)
- Avahi/mDNS is **enabled** for `adhan.local`
- Dua defaults to `short-authentic` — preview others under **Audio** and pick one

## Project layout

```
app/           FastAPI + scheduler + offline times
web/           Portal PWA
audio/dua/     Dua preview clips
avahi/         mDNS service file
scripts/       Hotspot helper
mobile/        Expo companion shell
docs/skill.md  Agent skill
```

## Audio licensing

See [AUDIO.md](AUDIO.md). Replace bundled recordings as needed before wide redistribution.

## License

[MIT](LICENSE)
