#!/bin/bash
# Adhan Player — One-time setup for Raspberry Pi
# Run after first boot: ./setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ACTUAL_USER=$(whoami)

echo "=== Adhan Player Setup ==="
echo "Directory: $SCRIPT_DIR"
echo "User: $ACTUAL_USER"

# 1. Install system dependencies
echo ""
echo "[1/7] Installing system packages..."
sudo apt update
sudo apt install -y mpv python3-venv curl git avahi-daemon avahi-utils network-manager iptables

# Prefer NetworkManager for Wi‑Fi / hotspot onboarding
if systemctl list-unit-files | grep -q NetworkManager.service; then
    sudo systemctl enable NetworkManager
    sudo systemctl start NetworkManager || true
fi

# 2. Create Python virtual environment
echo ""
echo "[2/7] Setting up Python environment..."
python3 -m venv "$SCRIPT_DIR/venv"
"$SCRIPT_DIR/venv/bin/pip" install --upgrade pip
"$SCRIPT_DIR/venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

# 3. Ensure audio dirs + default adhan if missing
echo ""
echo "[3/7] Checking audio files..."
mkdir -p "$SCRIPT_DIR/audio/dua" "$SCRIPT_DIR/cache"
if [ ! -f "$SCRIPT_DIR/audio/adhan.mp3" ]; then
    curl -L -o "$SCRIPT_DIR/audio/adhan.mp3" \
        "https://archive.org/download/AdhanMisharyRashid/Adhan%20Mishary%20Rashid.mp3"
    echo "  Downloaded default adhan audio"
else
    echo "  Adhan audio present"
fi

# 4. Cache directory
echo ""
echo "[4/7] Creating cache directory..."
mkdir -p "$SCRIPT_DIR/cache"

# 5. Power-saving (keep Avahi + NetworkManager)
echo ""
echo "[5/7] Applying power-saving settings (keeping Avahi + NetworkManager)..."

BOOT_CFG=""
for cfg in /boot/firmware/config.txt /boot/config.txt; do
    if [ -f "$cfg" ]; then BOOT_CFG="$cfg"; break; fi
done
if [ -n "$BOOT_CFG" ]; then
    grep -q "dtoverlay=disable-bt" "$BOOT_CFG" 2>/dev/null || \
        echo "dtoverlay=disable-bt" | sudo tee -a "$BOOT_CFG" > /dev/null
    grep -q "gpu_mem=16" "$BOOT_CFG" 2>/dev/null || \
        echo "gpu_mem=16" | sudo tee -a "$BOOT_CFG" > /dev/null
fi

# Do NOT disable avahi-daemon — needed for adhan.local discovery
for svc in triggerhappy bluetooth hciuart; do
    if systemctl is-enabled "$svc" &>/dev/null 2>&1; then
        sudo systemctl disable "$svc" 2>/dev/null || true
        sudo systemctl stop "$svc" 2>/dev/null || true
        echo "  Disabled $svc"
    fi
done

sudo systemctl enable avahi-daemon
sudo systemctl start avahi-daemon || true

# Hostname for http://adhan.local
if [ "$(hostname)" != "adhan" ]; then
    echo "  Setting hostname to adhan (for http://adhan.local)"
    sudo hostnamectl set-hostname adhan || true
fi

# Avahi service advertisement
if [ -d /etc/avahi/services ]; then
    sudo cp "$SCRIPT_DIR/avahi/adhan.service" /etc/avahi/services/adhan.service
    sudo systemctl restart avahi-daemon || true
    echo "  Installed Avahi _adhan._tcp service"
fi

sudo usermod -aG audio "$ACTUAL_USER" 2>/dev/null || true
# Polkit-less nmcli from the service user
sudo usermod -aG netdev "$ACTUAL_USER" 2>/dev/null || true

# Passwordless sudo for power mgmt + Wi‑Fi/hotspot/captive redirects + LED
SUDOERS_FILE="/etc/sudoers.d/adhan-player"
sudo tee "$SUDOERS_FILE" > /dev/null <<EOF
$ACTUAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/rtcwake
$ACTUAL_USER ALL=(ALL) NOPASSWD: /usr/bin/tvservice
$ACTUAL_USER ALL=(ALL) NOPASSWD: /usr/bin/nmcli
$ACTUAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/iptables
$ACTUAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/ip6tables
$ACTUAL_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl reload NetworkManager
$ACTUAL_USER ALL=(ALL) NOPASSWD: /usr/bin/mkdir
$ACTUAL_USER ALL=(ALL) NOPASSWD: /usr/bin/tee
$ACTUAL_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart adhan-player
$ACTUAL_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl try-restart adhan-player
$ACTUAL_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl daemon-reload
$ACTUAL_USER ALL=(ALL) NOPASSWD: /usr/bin/rm
EOF
sudo chmod 440 "$SUDOERS_FILE"
echo "  Configured passwordless sudo for power + Wi‑Fi onboarding"

# Allow NetworkManager shared-mode dnsmasq drop-ins
sudo mkdir -p /etc/NetworkManager/dnsmasq-shared.d

# 6. Install systemd service
echo ""
echo "[6/7] Installing systemd service..."
sed "s|User=pi|User=$ACTUAL_USER|g; s|/home/pi/adhan-player|$SCRIPT_DIR|g" \
    "$SCRIPT_DIR/adhan-player.service" | sudo tee /etc/systemd/system/adhan-player.service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable adhan-player
sudo systemctl restart adhan-player

# Nightly + boot git updates
sed "s|User=pi|User=$ACTUAL_USER|g; s|/home/pi/adhan-player|$SCRIPT_DIR|g" \
    "$SCRIPT_DIR/adhan-update.service" | sudo tee /etc/systemd/system/adhan-update.service > /dev/null
sudo cp "$SCRIPT_DIR/adhan-update.timer" /etc/systemd/system/adhan-update.timer
sudo systemctl daemon-reload
sudo systemctl enable adhan-update.service
sudo systemctl enable --now adhan-update.timer
echo "  Enabled boot + 00:08 auto-update timer"

# 7. Hotspot helper
echo ""
echo "[7/7] Hotspot helper..."
chmod +x "$SCRIPT_DIR/scripts/hotspot-setup.sh" "$SCRIPT_DIR/scripts/update.sh" "$SCRIPT_DIR/setup.sh" "$SCRIPT_DIR/prepare-sd.sh" 2>/dev/null || true

SSID_SUFFIX=$(cat /sys/class/net/wlan0/address 2>/dev/null | tr -d ':' | tail -c 5 | tr '[:lower:]' '[:upper:]')
SSID_SUFFIX="${SSID_SUFFIX:-XXXX}"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "If the Pi has home Wi‑Fi (Imager or already joined):"
echo "  Open http://adhan.local:8080"
echo ""
echo "If NOT on Wi‑Fi, the app auto-starts a setup hotspot (~75s):"
echo "  1. On your phone, join Wi‑Fi:  Adhan-${SSID_SUFFIX}"
echo "  2. Password:                  adhan-setup"
echo "  3. Open:                      http://10.42.0.1:8080/wifi"
echo "     (or wait for the captive “Sign in to network” prompt)"
echo "  4. Enter home Wi‑Fi → Connect"
echo "  5. Rejoin home Wi‑Fi on your phone → http://adhan.local:8080"
echo ""
echo "LED: slow blink = setup hotspot waiting; solid = online."
echo ""
echo "Useful commands:"
echo "  Status:    sudo systemctl status adhan-player"
echo "  Logs:      journalctl -u adhan-player -f"
echo "  Hotspot:   $SCRIPT_DIR/scripts/hotspot-setup.sh --info"
