#!/bin/bash
# Manual hotspot helper (the app also auto-starts this when offline).
# Usage:
#   sudo ./scripts/hotspot-setup.sh          # start
#   sudo ./scripts/hotspot-setup.sh --stop   # stop
#   ./scripts/hotspot-setup.sh --info        # print SSID / URL

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

if [ -x "$ROOT_DIR/venv/bin/python" ]; then
  PY="$ROOT_DIR/venv/bin/python"
else
  PY="python3"
fi

case "${1:-}" in
  --stop)
    "$PY" - <<'PY'
from app.wifi import stop_hotspot
print(stop_hotspot())
PY
    ;;
  --info)
    "$PY" - <<'PY'
from app.wifi import hotspot_ssid, wifi_status
print(f"SSID:     {hotspot_ssid()}")
print(f"Password: (none — open network)")
print(f"Setup:    http://10.42.0.1:8080/wifi")
print(f"LAN:      http://adhan.local:8080")
print(f"Status:   {wifi_status()}")
PY
    ;;
  *)
    "$PY" - <<'PY'
from app.wifi import start_hotspot
print(start_hotspot())
PY
    ;;
esac
