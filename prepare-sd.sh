#!/bin/bash
# prepare-sd.sh — Run on your Mac after flashing with Raspberry Pi Imager.
# Imager handles WiFi, SSH, and user creation.
# This script adds the adhan player files and a setup hook to firstrun.
#
# Usage:
#   1. Flash Raspberry Pi OS Lite (64-bit) with Raspberry Pi Imager
#      - Configure WiFi, SSH, username/password in Imager settings
#   2. Leave the SD card inserted (re-insert if auto-ejected)
#   3. Run: ./prepare-sd.sh
#   4. Eject SD card, plug into Pi, power on — done.

set -e

echo "=== Adhan Player — SD Card Prep ==="
echo ""

BOOT_VOL=""
for vol in /Volumes/bootfs /Volumes/boot; do
    if [ -f "$vol/cmdline.txt" ]; then
        BOOT_VOL="$vol"
        break
    fi
done

if [ -z "$BOOT_VOL" ]; then
    echo "ERROR: Could not find the Raspberry Pi boot partition."
    echo "Make sure the SD card is inserted and was flashed with Raspberry Pi OS."
    exit 1
fi

echo "Found boot partition: $BOOT_VOL"

read -p "What username did you set in Raspberry Pi Imager? (default: pi): " PI_USER
PI_USER="${PI_USER:-pi}"
echo ""

echo "Copying adhan-player files to SD card..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="$BOOT_VOL/adhan-player"
rm -rf "$DEST"
mkdir -p "$DEST"

# Copy project (exclude venv, cache, pyc)
rsync -a --exclude 'venv' --exclude '__pycache__' --exclude 'cache' --exclude '.git' \
    --exclude '.DS_Store' --exclude 'mobile/AdhanCompanion/node_modules' \
    "$SCRIPT_DIR/" "$DEST/" 2>/dev/null || {
    # Fallback without rsync
    mkdir -p "$DEST/audio/dua" "$DEST/app" "$DEST/web" "$DEST/avahi" "$DEST/scripts" "$DEST/docs"
    cp "$SCRIPT_DIR"/*.py "$SCRIPT_DIR"/*.txt "$SCRIPT_DIR"/*.json "$SCRIPT_DIR"/*.service "$SCRIPT_DIR"/*.sh "$DEST/" 2>/dev/null || true
    cp -R "$SCRIPT_DIR/app" "$DEST/"
    cp -R "$SCRIPT_DIR/web" "$DEST/"
    cp -R "$SCRIPT_DIR/avahi" "$DEST/"
    cp -R "$SCRIPT_DIR/scripts" "$DEST/"
    cp -R "$SCRIPT_DIR/docs" "$DEST/"
    cp -R "$SCRIPT_DIR/audio" "$DEST/" 2>/dev/null || true
    cp "$SCRIPT_DIR/LICENSE" "$SCRIPT_DIR/README.md" "$SCRIPT_DIR/AUDIO.md" "$SCRIPT_DIR/AGENTS.md" "$SCRIPT_DIR/llms.txt" "$DEST/" 2>/dev/null || true
}
echo "  Done"

echo "Creating adhan setup script..."
cat > "$BOOT_VOL/adhan-setup.sh" << SETUP_OUTER
#!/bin/bash
set -e
LOG="/var/log/adhan-setup.log"
exec > "\$LOG" 2>&1

echo "[\$(date)] Adhan setup starting..."

echo "Waiting for clock sync..."
for i in \$(seq 1 30); do
    YEAR=\$(date +%Y)
    if [ "\$YEAR" -ge 2025 ]; then
        echo "Clock synced: \$(date)"
        break
    fi
    echo "  Clock not ready (year=\$YEAR), waiting... (\$i/30)"
    systemctl restart systemd-timesyncd 2>/dev/null || true
    sleep 10
done
if [ "\$(date +%Y)" -lt 2025 ]; then
    echo "Clock sync failed, setting approximate time..."
    date -s "2026-10-04 00:00:00"
fi

USER_HOME="/home/${PI_USER}"
ADHAN_SRC=""
for src in /boot/firmware/adhan-player /boot/adhan-player; do
    [ -d "\$src" ] && ADHAN_SRC="\$src" && break
done

if [ -z "\$ADHAN_SRC" ]; then
    echo "ERROR: adhan-player files not found on boot partition"
    exit 1
fi

echo "Moving adhan-player to \$USER_HOME..."
cp -r "\$ADHAN_SRC" "\$USER_HOME/adhan-player"
chown -R ${PI_USER}:${PI_USER} "\$USER_HOME/adhan-player"
chmod +x "\$USER_HOME/adhan-player/setup.sh" "\$USER_HOME/adhan-player/scripts/"*.sh || true

echo "Installing system packages..."
apt-get update -qq
apt-get install -y -qq mpv python3-venv curl git avahi-daemon avahi-utils network-manager iptables > /dev/null 2>&1
systemctl enable NetworkManager 2>/dev/null || true
systemctl start NetworkManager 2>/dev/null || true

echo "Setting up Python environment..."
sudo -u ${PI_USER} python3 -m venv "\$USER_HOME/adhan-player/venv"
sudo -u ${PI_USER} "\$USER_HOME/adhan-player/venv/bin/pip" install --upgrade pip -q
sudo -u ${PI_USER} "\$USER_HOME/adhan-player/venv/bin/pip" install -r "\$USER_HOME/adhan-player/requirements.txt" -q

echo "Applying power-saving settings (keeping Avahi + NetworkManager)..."
BOOT_CFG=""
for cfg in /boot/firmware/config.txt /boot/config.txt; do
    [ -f "\$cfg" ] && BOOT_CFG="\$cfg" && break
done
if [ -n "\$BOOT_CFG" ]; then
    grep -q "dtoverlay=disable-bt" "\$BOOT_CFG" || echo "dtoverlay=disable-bt" >> "\$BOOT_CFG"
    grep -q "gpu_mem=16" "\$BOOT_CFG" || echo "gpu_mem=16" >> "\$BOOT_CFG"
fi

for svc in triggerhappy bluetooth hciuart; do
    systemctl disable "\$svc" 2>/dev/null || true
    systemctl stop "\$svc" 2>/dev/null || true
done

systemctl enable avahi-daemon
systemctl start avahi-daemon || true
hostnamectl set-hostname adhan || true
if [ -d /etc/avahi/services ]; then
    cp "\$USER_HOME/adhan-player/avahi/adhan.service" /etc/avahi/services/adhan.service
    systemctl restart avahi-daemon || true
fi

mkdir -p /etc/NetworkManager/dnsmasq-shared.d
cat > /etc/sudoers.d/adhan-player <<EOF
${PI_USER} ALL=(ALL) NOPASSWD: /usr/sbin/rtcwake
${PI_USER} ALL=(ALL) NOPASSWD: /usr/bin/tvservice
${PI_USER} ALL=(ALL) NOPASSWD: /usr/bin/nmcli
${PI_USER} ALL=(ALL) NOPASSWD: /usr/sbin/iptables
${PI_USER} ALL=(ALL) NOPASSWD: /usr/sbin/ip6tables
${PI_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl reload NetworkManager
${PI_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart adhan-player
${PI_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl try-restart adhan-player
${PI_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl daemon-reload
${PI_USER} ALL=(ALL) NOPASSWD: /usr/bin/mkdir
${PI_USER} ALL=(ALL) NOPASSWD: /usr/bin/tee
${PI_USER} ALL=(ALL) NOPASSWD: /usr/bin/rm
EOF
chmod 440 /etc/sudoers.d/adhan-player
usermod -aG audio,netdev ${PI_USER} 2>/dev/null || true

echo "Installing adhan-player service..."
ADHAN_DEST="\$USER_HOME/adhan-player"
sed "s|User=pi|User=${PI_USER}|g; s|/home/pi/adhan-player|\$ADHAN_DEST|g" \
    "\$ADHAN_DEST/adhan-player.service" > /etc/systemd/system/adhan-player.service
systemctl daemon-reload
systemctl enable adhan-player
systemctl start adhan-player

sed "s|User=pi|User=${PI_USER}|g; s|/home/pi/adhan-player|\$ADHAN_DEST|g" \
    "\$ADHAN_DEST/adhan-update.service" > /etc/systemd/system/adhan-update.service
cp "\$ADHAN_DEST/adhan-update.timer" /etc/systemd/system/adhan-update.timer
systemctl daemon-reload
systemctl enable adhan-update.service
systemctl enable --now adhan-update.timer

echo "Cleaning up..."
rm -rf /boot/firmware/adhan-player /boot/adhan-player 2>/dev/null || true
rm -f /etc/systemd/system/adhan-setup.service
systemctl daemon-reload

echo "[\$(date)] Adhan setup complete!"
echo "If online: http://adhan.local:8080"
echo "If offline: join open SSID Adhan-XXXX (no password) then http://10.42.0.1:8080/wifi"
SETUP_OUTER
chmod +x "$BOOT_VOL/adhan-setup.sh"
echo "  Done"

echo "Creating first-boot service..."
cat > "$BOOT_VOL/adhan-setup.service" << 'SVC'
[Unit]
Description=Adhan Player First-Boot Setup
After=network-online.target
Wants=network-online.target
ConditionPathExists=/boot/firmware/adhan-setup.sh

[Service]
Type=oneshot
ExecStart=/boot/firmware/adhan-setup.sh
RemainAfterExit=no

[Install]
WantedBy=multi-user.target
SVC
echo "  Done"

FIRSTRUN="$BOOT_VOL/firstrun.sh"
if [ -f "$FIRSTRUN" ]; then
    echo "Hooking into Imager's firstrun.sh..."
    cat >> "$FIRSTRUN" << 'HOOK'

# --- Adhan Player: install setup service to run on next boot ---
cp /boot/firmware/adhan-setup.service /etc/systemd/system/adhan-setup.service
systemctl daemon-reload
systemctl enable adhan-setup.service
HOOK
    echo "  Done"
else
    echo "WARNING: No Imager firstrun.sh found."
    echo "  SSH in and run setup.sh manually."
fi

echo ""
echo "=== SD Card Ready ==="
echo ""
echo "  1. Eject the SD card"
echo "  2. Insert into Raspberry Pi + speaker"
echo "  3. Power on"
echo ""
echo "First boot: WiFi/SSH (Imager optional), reboot."
echo "Second boot: Adhan player installs (~3-5 min)."
echo ""
echo "If Imager Wi‑Fi worked:  http://adhan.local:8080"
echo "If not: phone joins Adhan-XXXX (open, no password) → http://10.42.0.1:8080/wifi"
echo "  (ACT LED slow-blinks while waiting on the setup hotspot)"
echo ""
echo "SSH: ssh ${PI_USER}@adhan.local"
