# Skill: Configure Adhan Player

## When to use

Use this skill when the user wants to set up, move, mute, or change audio on a local Adhan Player device.

## Preconditions

- Device reachable at `http://adhan.local:8080` or a known LAN IP
- Same Wi‑Fi as the user (no cloud relay)

## Procedure

### 0. Not on Wi‑Fi yet?

Ask the user to join hotspot `Adhan-XXXX` / `adhan-setup`, then:

```bash
curl -s http://10.42.0.1:8080/api/wifi/setup-info
curl -s http://10.42.0.1:8080/api/wifi/connect -X POST \
  -H 'Content-Type: application/json' \
  -d '{"ssid":"<home>","password":"<psk>"}'
```

Then continue on `http://adhan.local:8080` after the phone rejoins home Wi‑Fi.

### 1. Health check

```bash
curl -s http://adhan.local:8080/api/health
curl -s http://adhan.local:8080/api/status
```

If DNS fails, retry with the IP from the user’s QR code / router.

### 2. Choose post-adhan dua

```bash
curl -s http://adhan.local:8080/api/duas | jq .
curl -s http://adhan.local:8080/api/play -X POST \
  -H 'Content-Type: application/json' \
  -d '{"kind":"dua","dua_id":"short-authentic"}'
```

Repeat for `with-translation`, `slow-teach`, `masjid-wording`. Ask which they prefer.

### 3. Apply settings

```bash
curl -s http://adhan.local:8080/api/config -X PATCH \
  -H 'Content-Type: application/json' \
  -d '{
    "setup_complete": true,
    "location_name": "<city>",
    "latitude": <lat>,
    "longitude": <lon>,
    "timezone": "<IANA tz>",
    "method": 2,
    "school": 1,
    "volume": 80,
    "fajr_volume": 50,
    "dua_enabled": true,
    "dua_id": "<chosen id>",
    "sleep_enabled": false
  }'
```

### 4. Verify schedule

```bash
curl -s http://adhan.local:8080/api/schedule | jq .
```

### 5. Daily controls

```bash
# Mute for an hour
curl -s http://adhan.local:8080/api/mute -X POST \
  -H 'Content-Type: application/json' -d '{"minutes":60}'

# Skip next prayer audio
curl -s http://adhan.local:8080/api/skip -X POST -d '{}'

# Stop current playback
curl -s http://adhan.local:8080/api/stop -X POST -d '{}'
```

## System prompt snippet

> You are configuring a local Adhan Player on the user’s LAN. Use HTTP APIs at http://adhan.local:8080. Prefer PATCH /api/config and POST /api/play. Do not require SSH. Keep sleep_enabled false unless asked.

## References

- OpenAPI: `/openapi.json`
- Agent notes: `/AGENTS.md`
- Compact index: `/llms.txt`
