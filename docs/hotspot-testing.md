# Setup hotspot testing

The first-boot AP is an open NetworkManager Wi-Fi hotspot named `Adhan-XXXX` (last 4 of the wlan MAC) at `10.42.0.1`. Phones should get DHCP, open a captive sheet or `http://10.42.0.1:8080/wifi`, pick home Wi-Fi, then the Pi joins that network and the phone switches back.

## What often went wrong

- The adhan service waited on `network-online.target`, so the portal (and hotspot watchdog) started late when there was no LAN.
- `start_hotspot` reloaded NetworkManager *after* the AP was up, which dropped beacons.
- `ipv4.method=shared` needs `dnsmasq-base`. Without it, the SSID appears but phones never get `10.42.0.1`.
- dhcpcd and NetworkManager both owning `wlan0` fights AP mode.
- Captive probes (`/generate_204`, `/hotspot-detect.html`) were 302-redirected; several phone OS builds ignore that.
- Leaving AP mode and joining home Wi-Fi used a 2 second sleep and a single `nmcli device wifi connect`, which often raced the radio.

## Software checks (no Pi radio required)

```bash
python -m pytest tests/test_wifi_parse.py tests/test_captive.py tests/test_api.py -q
```

On a machine with `nmcli`:

```bash
python - <<'PY'
from app.wifi import hotspot_ssid, hotspot_wait_secs, wifi_status
print("SSID would be", hotspot_ssid())
print("wait with no saved nets", hotspot_wait_secs({"wifi_offline_wait_secs": 75}, 0))
print("wait with saved nets", hotspot_wait_secs({"wifi_offline_wait_secs": 75}, 1))
print(wifi_status())
PY
```

Expect about 12s wait when there are no saved station profiles, and the configured wait (default 75s) when there are.

## Physical Pi test

These steps need a Raspberry Pi with a Wi-Fi radio and a phone.

### A. Hotspot appears on first boot (no home Wi-Fi)

1. Flash / install as usual, but skip Imager Wi-Fi (or forget all NM wifi profiles).
2. Power on. Confirm `adhan-player.service` does **not** wait on `network-online`.
3. Within about 20-40 seconds of the app starting, the Pi ACT LED should slow-blink.
4. Phone Wi-Fi list should show open `Adhan-XXXX` (no password).
5. Join it. The phone should get `10.42.0.x`. Check: phone browser `http://10.42.0.1:8080/api/wifi` shows `"mode": "hotspot"` and `"dhcp_ready": true`.
6. Captive “Sign in to network” should open `/wifi`. If not, open `http://10.42.0.1:8080/wifi` manually.

### B. Hand off to home Wi-Fi

1. On `/wifi`, pick or type the home SSID, enter the password, Connect.
2. The setup AP will drop (phone disconnects). That is expected.
3. If the password is wrong, `Adhan-XXXX` should come back within about 15 seconds so you can retry.
4. If the password is right: phone rejoins home Wi-Fi, then open `http://adhan.local` (port 80 or `:8080`).
5. `GET /api/wifi` should show `"mode": "station"` and the home SSID.

### C. Home Wi-Fi later fails

1. With the Pi already on home Wi-Fi, turn off that AP or change the PSK.
2. Within about a minute the watchdog should raise `Adhan-XXXX` again.

### D. Packages and conflicts

On the Pi:

```bash
dpkg -l dnsmasq-base network-manager dhcpcd5 | cat
systemctl is-enabled dhcpcd || true
systemctl is-active NetworkManager
nmcli device status
iw dev wlan0 get power_save
```

Expect `dnsmasq-base` installed, `dhcpcd` disabled/inactive, NetworkManager active, `wlan0` managed by NM, power_save off while the AP is up.

### E. Forced hotspot

```bash
./scripts/hotspot-setup.sh --info
./scripts/hotspot-setup.sh
curl -s http://10.42.0.1:8080/api/wifi/setup-info
./scripts/hotspot-setup.sh --stop
```

Do not run `systemctl reload NetworkManager` while the AP is up; that is what used to make the SSID vanish.
