#!/bin/bash
# Fallback Wi-Fi setup hotspot for first boot when the Pi has no internet.
# Creates SSID Adhan-XXXX (last 4 of MAC) with password adhan-setup
# Captive clients are redirected to the portal once NetworkManager is available.
#
# Usage (on the Pi, as root or with sudo):
#   sudo ./scripts/hotspot-setup.sh
#   sudo ./scripts/hotspot-setup.sh --stop

set -euo pipefail

SSID_PREFIX="Adhan"
PASS="adhan-setup"
CONN_NAME="adhan-setup-hotspot"

mac_suffix() {
  local mac
  mac=$(cat /sys/class/net/wlan0/address 2>/dev/null | tr -d ':' | tail -c 5 || echo "0000")
  echo "${mac^^}"
}

stop_hotspot() {
  if command -v nmcli >/dev/null 2>&1; then
    nmcli connection down "$CONN_NAME" 2>/dev/null || true
    nmcli connection delete "$CONN_NAME" 2>/dev/null || true
  fi
  echo "Hotspot stopped (if it was running)."
}

start_hotspot() {
  if ! command -v nmcli >/dev/null 2>&1; then
    echo "NetworkManager (nmcli) not found."
    echo "On Raspberry Pi OS Bookworm+, install: sudo apt install network-manager"
    echo "Or configure Wi-Fi with Raspberry Pi Imager before first boot."
    exit 1
  fi

  local ssid="${SSID_PREFIX}-$(mac_suffix)"
  echo "Creating hotspot SSID: $ssid  password: $PASS"

  nmcli connection delete "$CONN_NAME" 2>/dev/null || true
  nmcli connection add \
    type wifi ifname wlan0 con-name "$CONN_NAME" autoconnect no ssid "$ssid"
  nmcli connection modify "$CONN_NAME" \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    ipv4.method shared \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$PASS"
  nmcli connection up "$CONN_NAME"

  echo ""
  echo "Connect a phone to Wi-Fi: $ssid / $PASS"
  echo "Then open: http://10.42.0.1:8080  (typical NM shared IP)"
  echo "Or: http://adhan.local:8080"
  echo ""
  echo "After joining the home Wi-Fi via the portal/Imager, run:"
  echo "  sudo $0 --stop"
}

case "${1:-}" in
  --stop) stop_hotspot ;;
  *) start_hotspot ;;
esac
