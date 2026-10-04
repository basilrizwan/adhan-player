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
sudo apt install -y mpv python3-venv curl avahi-daemon avahi-utils

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

# 5. Power-saving (keep Avahi enabled for discovery)
echo ""
echo "[5/7] Applying power-saving settings (keeping Avahi)..."

if ! grep -q "dtoverlay=disable-bt" /boot/firmware/config.txt 2>/dev/null; then
    echo "dtoverlay=disable-bt" | sudo tee -a /boot/firmware/config.txt > /dev/null
    echo "  Disabled Bluetooth"
fi

if ! grep -q "gpu_mem=16" /boot/firmware/config.txt 2>/dev/null; then
    echo "gpu_mem=16" | sudo tee -a /boot/firmware/config.txt > /dev/null
    echo "  Reduced GPU memory to 16MB"
fi

if command -v iwconfig &>/dev/null; then
    sudo iwconfig wlan0 power off 2>/dev/null || true
    echo "  Disabled Wi-Fi power management"
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
    if ! grep -q "adhan" /etc/hosts 2>/dev/null; then
        echo "10.0.0.1 adhan" | sudo tee -a /etc/hosts >/dev/null || true
        # Prefer mapping via avahi; hosts line is best-effort
    fi
fi

# Avahi service advertisement
if [ -d /etc/avahi/services ]; then
    sudo cp "$SCRIPT_DIR/avahi/adhan.service" /etc/avahi/services/adhan.service
    sudo systemctl restart avahi-daemon || true
    echo "  Installed Avahi _adhan._tcp service"
fi

sudo usermod -aG audio "$ACTUAL_USER" 2>/dev/null || true

SUDOERS_FILE="/etc/sudoers.d/adhan-player"
echo "$ACTUAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/rtcwake, /usr/bin/tvservice, /usr/bin/tee /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor, /usr/bin/tee /sys/class/leds/ACT/brightness" \
    | sudo tee "$SUDOERS_FILE" > /dev/null
sudo chmod 440 "$SUDOERS_FILE"
echo "  Configured passwordless sudo for optional power management"

# 6. Install systemd service
echo ""
echo "[6/7] Installing systemd service..."
sed "s|User=pi|User=$ACTUAL_USER|g; s|/home/pi/adhan-player|$SCRIPT_DIR|g" \
    "$SCRIPT_DIR/adhan-player.service" | sudo tee /etc/systemd/system/adhan-player.service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable adhan-player
sudo systemctl restart adhan-player

# 7. Hotspot helper permissions
echo ""
echo "[7/7] Hotspot helper..."
chmod +x "$SCRIPT_DIR/scripts/hotspot-setup.sh" "$SCRIPT_DIR/setup.sh" "$SCRIPT_DIR/prepare-sd.sh" 2>/dev/null || true
echo "  If Wi-Fi was not set in Imager: sudo $SCRIPT_DIR/scripts/hotspot-setup.sh"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Open the portal from a phone on the same Wi-Fi:"
echo "  http://adhan.local:8080"
echo "  (or http://<pi-ip>:8080)"
echo ""
echo "Useful commands:"
echo "  Status:    sudo systemctl status adhan-player"
echo "  Logs:      journalctl -u adhan-player -f"
echo "  API docs:  http://adhan.local:8080/docs"
echo "  Agent doc: http://adhan.local:8080/llms.txt"
