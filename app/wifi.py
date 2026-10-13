"""Wi-Fi / hotspot helpers via NetworkManager (nmcli) for headless setup."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from app.config import CACHE_DIR

log = logging.getLogger("adhan.wifi")

HOTSPOT_CONN = "adhan-setup-hotspot"
SSID_PREFIX = "Adhan"
HOTSPOT_IP = "10.42.0.1"
HOTSPOT_CIDR = "10.42.0.1/24"
# 2.4 GHz channel 6 is widely usable on Pi radios and phone clients.
HOTSPOT_CHANNEL = "6"
WATCHDOG_INTERVAL_SECS = int(os.environ.get("ADHAN_WIFI_WATCHDOG_SECS", "60"))
HOTSPOT_RETRY_SECS = int(os.environ.get("ADHAN_HOTSPOT_RETRY_SECS", "300"))

_lock = threading.RLock()
_watchdog_thread: threading.Thread | None = None
_watchdog_stop = threading.Event()
_led_thread: threading.Thread | None = None
_led_stop = threading.Event()
_led_mode = "idle"  # idle | hotspot | online | error
_connect_state: dict[str, Any] = {
    "busy": False,
    "phase": "idle",  # idle | connecting | succeeded | failed
    "ssid": None,
    "error": None,
    "wifi": None,
}
_hotspot_cache = {"ts": 0.0, "active": False}
_HOTSPOT_CACHE_TTL = 1.5
_last_scan_meta: dict[str, Any] = {"source": "none", "count": 0}


def _run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, returncode=127, stdout="", stderr="not found")


def has_nmcli() -> bool:
    return _run(["which", "nmcli"]).returncode == 0


def _ensure_sudo_nmcli() -> list[str]:
    """Prefix with sudo when not root."""
    if os.geteuid() == 0:
        return []
    return ["sudo", "-n"]


def _nm(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return _run(_ensure_sudo_nmcli() + args, timeout=timeout)


def mac_suffix() -> str:
    for path in (
        Path("/sys/class/net/wlan0/address"),
        Path("/sys/class/net/wlan1/address"),
    ):
        try:
            mac = path.read_text().strip().replace(":", "")
            if len(mac) >= 4:
                return mac[-4:].upper()
        except OSError:
            continue
    return "0000"


def hotspot_ssid() -> str:
    return f"{SSID_PREFIX}-{mac_suffix()}"


def hotspot_password() -> str:
    """Setup hotspot is open (no password) so phones can join without a sticker PSK."""
    return ""


def wait_for_networkmanager(timeout: float = 30.0) -> bool:
    """Wait until nmcli can talk to NetworkManager (boot race)."""
    if not has_nmcli():
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = _nm(["nmcli", "general", "status"], timeout=8)
        if r.returncode == 0 and r.stdout.strip():
            return True
        time.sleep(1)
    log.warning("NetworkManager did not become ready within %ss", int(timeout))
    return False


def _invalidate_hotspot_cache() -> None:
    with _lock:
        _hotspot_cache["ts"] = 0.0


def is_hotspot_active() -> bool:
    if not has_nmcli():
        return False
    r = _nm(["nmcli", "-t", "-f", "NAME,DEVICE,TYPE", "connection", "show", "--active"])
    for line in r.stdout.splitlines():
        parts = line.split(":")
        if parts and parts[0] == HOTSPOT_CONN:
            return True
    return False


def hotspot_active_cached(ttl: float = _HOTSPOT_CACHE_TTL) -> bool:
    """Cached hotspot check so captive middleware does not shell out on every request."""
    now = time.time()
    with _lock:
        if now - _hotspot_cache["ts"] < ttl:
            return bool(_hotspot_cache["active"])
    active = is_hotspot_active()
    with _lock:
        _hotspot_cache["ts"] = now
        _hotspot_cache["active"] = active
    return active


def wifi_device() -> str | None:
    if not has_nmcli():
        return None
    r = _nm(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"])
    fallback = None
    for line in r.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[1] == "wifi":
            state = parts[2]
            if "unmanaged" in state:
                fallback = parts[0]
                continue
            return parts[0]
    return fallback or "wlan0"


def current_ssid() -> str | None:
    if not has_nmcli():
        return None
    r = _nm(["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi"])
    for line in r.stdout.splitlines():
        # ACTIVE:SSID. SSID may contain colons rarely; split once
        if line.startswith("yes:"):
            ssid = line[4:]
            return ssid or None
    r2 = _nm(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"])
    for line in r2.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[1] == "802-11-wireless" and parts[0] != HOTSPOT_CONN:
            return parts[0]
    return None


def has_default_route() -> bool:
    r = _run(["ip", "route", "show", "default"])
    return bool(r.stdout.strip())


def has_internet(timeout: float = 3.0) -> bool:
    """Cheap connectivity check: DNS or TCP to a public resolver."""
    import socket

    try:
        sock = socket.create_connection(("1.1.1.1", 53), timeout=timeout)
        sock.close()
        return True
    except OSError:
        pass
    try:
        sock = socket.create_connection(("8.8.8.8", 53), timeout=timeout)
        sock.close()
        return True
    except OSError:
        return False


def is_station_connected() -> bool:
    """Connected to a normal Wi-Fi AP (not our setup hotspot)."""
    if is_hotspot_active():
        return False
    ssid = current_ssid()
    if not ssid:
        return False
    return has_default_route()


def connect_progress() -> dict[str, Any]:
    with _lock:
        return dict(_connect_state)


def _has_hotspot_ip(dev: str | None = None) -> bool:
    iface = dev or wifi_device() or "wlan0"
    r = _run(["ip", "-4", "addr", "show", "dev", iface])
    return HOTSPOT_IP in (r.stdout or "")


def saved_wifi_connections() -> list[str]:
    """Station profiles (not the setup AP), most recently used first."""
    if not has_nmcli():
        return []
    r = _nm(["nmcli", "-t", "-f", "NAME,TYPE,TIMESTAMP", "connection", "show"])
    rows: list[tuple[int, str]] = []
    for line in r.stdout.splitlines():
        parts = re.split(r"(?<!\\):", line)
        if len(parts) < 2:
            continue
        name = parts[0].replace("\\:", ":")
        ctype = parts[1]
        if ctype != "802-11-wireless" or name == HOTSPOT_CONN:
            continue
        ts = 0
        if len(parts) >= 3:
            try:
                ts = int(parts[2])
            except ValueError:
                ts = 0
        rows.append((ts, name))
    rows.sort(reverse=True)
    return [name for _, name in rows]


def _active_station_connection() -> str | None:
    r = _nm(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"])
    for line in r.stdout.splitlines():
        name, _, ctype = line.rpartition(":")
        if ctype == "802-11-wireless" and name and name != HOTSPOT_CONN:
            return name.replace("\\:", ":")
    return None


def _bring_up_saved(name: str, timeout: int = 45) -> bool:
    log.info("Trying saved Wi-Fi connection %s", name)
    r = _nm(["nmcli", "connection", "up", name], timeout=timeout)
    if r.returncode != 0:
        log.info(
            "Saved connection %s did not come up: %s",
            name,
            (r.stderr or r.stdout).strip()[:200],
        )
        return False
    for _ in range(20):
        if has_default_route():
            break
        time.sleep(0.5)
    set_led_mode("online" if has_internet() else "idle")
    return True


def _friendly_nmcli_error(raw: str) -> str:
    text = raw.strip()
    low = text.lower()
    if "secrets were required" in low or "802-1x supplicant" in low or "psk" in low:
        return "Wrong Wi-Fi password (or the network needs a password)."
    if "no network with ssid" in low:
        return "Could not find that network. Check the name, move the speaker closer, or tick Hidden network."
    if "timeout" in low or "timed out" in low:
        return "The router did not answer in time. Move the speaker closer and try again."
    return text or "Failed to connect"


def _hotspot_has_clients() -> bool | None:
    """True if a phone is joined to the setup hotspot; None if we cannot tell."""
    dev = wifi_device() or "wlan0"
    r = _nm(["iw", "dev", dev, "station", "dump"], timeout=10)
    if r.returncode == 0:
        return "Station " in (r.stdout or "")
    r = _run(["ip", "neigh", "show", "dev", dev])
    if r.returncode == 0:
        return any(
            line.startswith("10.42.") and ("REACHABLE" in line or "DELAY" in line)
            for line in r.stdout.splitlines()
        )
    return None


def retry_home_wifi() -> bool:
    """While the setup hotspot is idle, try saved home networks (router booting slower than the Pi)."""
    saved = saved_wifi_connections()[:2]
    if not saved:
        return False
    with _lock:
        if _connect_state.get("busy") or not is_hotspot_active():
            return False
        log.info("Hotspot idle; retrying saved Wi-Fi: %s", ", ".join(saved))
        _nm(["nmcli", "connection", "down", HOTSPOT_CONN], timeout=20)
        _disable_captive_redirects()
        _invalidate_hotspot_cache()
        time.sleep(2)
        for name in saved:
            if _bring_up_saved(name):
                log.info("Rejoined home Wi-Fi via %s", name)
                return True
    log.info("Home Wi-Fi still unavailable; restarting setup hotspot")
    start_hotspot()
    return False


def hotspot_wait_secs(cfg: dict[str, Any], saved_count: int | None = None) -> int:
    """Shorter wait when there is nothing to connect to (first boot)."""
    configured = int(cfg.get("wifi_offline_wait_secs", 75))
    if saved_count is None:
        saved_count = len(saved_wifi_connections())
    if saved_count <= 0:
        return min(12, max(8, configured if configured < 12 else 12))
    return max(15, configured)


def wifi_status() -> dict[str, Any]:
    hotspot = is_hotspot_active()
    ssid = current_ssid()
    online = (not hotspot) and has_internet()
    station = is_station_connected()
    saved = saved_wifi_connections() if has_nmcli() else []
    return {
        "nmcli": has_nmcli(),
        "device": wifi_device(),
        "mode": "hotspot" if hotspot else ("station" if station else "offline"),
        "hotspot_active": hotspot,
        "hotspot_ssid": hotspot_ssid(),
        "hotspot_password": hotspot_password(),
        "hotspot_url": f"http://{HOTSPOT_IP}:8080/wifi",
        "hotspot_ip": HOTSPOT_IP,
        "dhcp_ready": _has_hotspot_ip() if hotspot else None,
        "ssid": None if hotspot else ssid,
        "has_route": has_default_route(),
        "online": online,
        "setup_needed": hotspot or not station,
        "captive": hotspot,
        "saved_connections": saved,
        "scan": dict(_last_scan_meta),
        "connect": connect_progress(),
    }


def _scan_cache_path() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / "wifi-scan.json"


def _save_scan_cache(networks: list[dict[str, Any]]) -> None:
    if not networks:
        return
    import json
    from datetime import datetime

    try:
        _scan_cache_path().write_text(
            json.dumps(
                {"scanned_at": datetime.now().isoformat(timespec="seconds"), "networks": networks},
                indent=2,
            )
            + "\n"
        )
    except OSError as e:
        log.warning("Could not save Wi-Fi scan cache: %s", e)


def _load_scan_cache() -> list[dict[str, Any]]:
    import json

    path = _scan_cache_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        nets = data.get("networks") or []
        return [n for n in nets if isinstance(n, dict) and n.get("ssid")]
    except Exception:
        return []


def _parse_nmcli_wifi_stdout(stdout: str) -> list[dict[str, Any]]:
    networks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in stdout.splitlines():
        fields = re.split(r"(?<!\\):", line)
        fields = [f.replace("\\:", ":") for f in fields]
        if len(fields) < 4:
            continue
        ssid, signal, security, in_use = fields[0], fields[1], fields[2], fields[3]
        if not ssid or ssid in seen:
            continue
        if ssid.startswith(SSID_PREFIX + "-"):
            continue
        seen.add(ssid)
        try:
            sig = int(signal)
        except ValueError:
            sig = 0
        networks.append(
            {
                "ssid": ssid,
                "signal": sig,
                "security": security or "",
                "in_use": in_use == "*",
            }
        )
    networks.sort(key=lambda n: (-n["signal"], n["ssid"].lower()))
    return networks


def _nmcli_wifi_list(*, rescan: bool) -> list[dict[str, Any]]:
    cmd = [
        "nmcli",
        "-t",
        "-f",
        "SSID,SIGNAL,SECURITY,IN-USE",
        "device",
        "wifi",
        "list",
    ]
    if rescan:
        cmd += ["--rescan", "yes"]
    r = _nm(cmd, timeout=45)
    if r.returncode != 0:
        log.warning("nmcli wifi list failed: %s", (r.stderr or r.stdout).strip())
        return []
    return _parse_nmcli_wifi_stdout(r.stdout)


def _iw_scan() -> list[dict[str, Any]]:
    """Best-effort scan while AP mode is up (Pi firmware sometimes still reports BSS)."""
    dev = wifi_device() or "wlan0"
    r = _nm(["iw", "dev", dev, "scan"], timeout=25)
    if r.returncode != 0:
        log.info("iw scan skipped/failed: %s", (r.stderr or r.stdout).strip()[:200])
        return []
    networks: list[dict[str, Any]] = []
    seen: set[str] = set()
    ssid = ""
    signal = 0
    security = ""
    for raw in (r.stdout or "").splitlines():
        line = raw.strip()
        if line.startswith("BSS ") and ssid:
            if ssid not in seen and not ssid.startswith(SSID_PREFIX + "-"):
                seen.add(ssid)
                networks.append({"ssid": ssid, "signal": signal, "security": security, "in_use": False})
            ssid, signal, security = "", 0, ""
        if line.startswith("SSID:"):
            ssid = line.split("SSID:", 1)[1].strip()
        elif line.startswith("signal:"):
            try:
                dbm = float(line.split()[1])
                signal = int(min(100, max(0, 2 * (dbm + 100))))
            except (IndexError, ValueError):
                signal = 0
        elif line.startswith("RSN:") or line.startswith("WPA:"):
            security = "WPA"
    if ssid and ssid not in seen and not ssid.startswith(SSID_PREFIX + "-"):
        networks.append({"ssid": ssid, "signal": signal, "security": security, "in_use": False})
    networks.sort(key=lambda n: (-n["signal"], n["ssid"].lower()))
    return networks


def scan_networks(rescan: bool = True) -> list[dict[str, Any]]:
    """List nearby Wi-Fi networks. Uses a pre-hotspot cache because AP mode often cannot scan."""
    global _last_scan_meta
    if not has_nmcli():
        cached = _load_scan_cache()
        _last_scan_meta = {"source": "cache" if cached else "none", "count": len(cached)}
        return cached

    with _lock:
        live: list[dict[str, Any]] = []
        hotspot = is_hotspot_active()
        source = "none"
        # Rescan while AP is up usually returns empty and can wipe NM's list.
        live = _nmcli_wifi_list(rescan=rescan and not hotspot)
        if live:
            source = "nmcli"
        if not live:
            live = _nmcli_wifi_list(rescan=False)
            if live:
                source = "nmcli-cached"
        if not live:
            live = _iw_scan()
            if live:
                source = "iw"
        if live:
            _save_scan_cache(live)
            _last_scan_meta = {"source": source, "count": len(live)}
            return live
        cached = _load_scan_cache()
        if cached:
            log.info("Using cached Wi-Fi scan (%s networks) because live scan is empty", len(cached))
        _last_scan_meta = {"source": "cache" if cached else "none", "count": len(cached)}
        return cached


def _connection_exists(name: str) -> bool:
    r = _nm(["nmcli", "-t", "-f", "NAME", "connection", "show"])
    for line in r.stdout.splitlines():
        if line == name:
            return True
    return False


def _prepare_radio(dev: str) -> None:
    _nm(["nmcli", "radio", "wifi", "on"])
    _nm(["rfkill", "unblock", "wifi"])
    _nm(["nmcli", "device", "set", dev, "managed", "yes"])
    # powersave 2 = ignore / disable. Helps AP beacons stay visible.
    _nm(["iw", "dev", dev, "set", "power_save", "off"])


def _write_dnsmasq_captive(*, reload_nm: bool = False) -> None:
    """Point all DNS names at the hotspot IP so captive browsers open our page."""
    conf_dir = Path("/etc/NetworkManager/dnsmasq-shared.d")
    conf = conf_dir / "adhan-captive.conf"
    try:
        if not conf_dir.is_dir():
            _nm(["mkdir", "-p", str(conf_dir)])
        content = f"# Adhan Player captive DNS\naddress=/#/{HOTSPOT_IP}\n"
        proc = subprocess.run(
            _ensure_sudo_nmcli() + ["tee", str(conf)],
            input=content,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            log.warning("Could not write dnsmasq captive config: %s", proc.stderr)
            return
        if reload_nm:
            # Only reload when the AP is down. Reloading NM while the AP is up
            # drops beacons and is a common cause of a "finicky" hotspot.
            _nm(["systemctl", "reload", "NetworkManager"])
    except Exception as e:
        log.warning("dnsmasq captive setup failed: %s", e)


def _clear_dnsmasq_captive() -> None:
    conf = Path("/etc/NetworkManager/dnsmasq-shared.d/adhan-captive.conf")
    if conf.exists():
        _nm(["rm", "-f", str(conf)])


def enable_http80_redirect() -> None:
    """http://adhan.local uses port 80; the app listens on 8080."""
    spec = [
        "-t",
        "nat",
        "-A",
        "PREROUTING",
        "-p",
        "tcp",
        "--dport",
        "80",
        "-j",
        "REDIRECT",
        "--to-port",
        "8080",
    ]
    for proto in ("iptables", "ip6tables"):
        check = spec.copy()
        check[check.index("-A")] = "-C"
        exists = _nm([proto] + check)
        if exists.returncode != 0:
            r = _nm([proto] + spec)
            if r.returncode != 0:
                log.warning("%s port-80 redirect failed: %s", proto, (r.stderr or "").strip())
            else:
                log.info("%s: redirecting TCP/80 to 8080 (adhan.local)", proto)


def _enable_captive_redirects() -> None:
    """Captive DNS plus TCP/80 to 8080 so phones open the setup page."""
    enable_http80_redirect()
    _write_dnsmasq_captive(reload_nm=False)


def _disable_captive_redirects() -> None:
    # Keep the port-80 redirect so http://adhan.local still works on the LAN.
    _clear_dnsmasq_captive()


def _wait_hotspot_ready(dev: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_hotspot_active() and _has_hotspot_ip(dev):
            return True
        time.sleep(0.4)
    return is_hotspot_active()


def _modify_hotspot_settings(ssid: str, dev: str) -> subprocess.CompletedProcess:
    return _nm(
        [
            "nmcli",
            "connection",
            "modify",
            HOTSPOT_CONN,
            "connection.interface-name",
            dev,
            "connection.autoconnect",
            "no",
            "802-11-wireless.ssid",
            ssid,
            "802-11-wireless.mode",
            "ap",
            "802-11-wireless.band",
            "bg",
            "802-11-wireless.channel",
            HOTSPOT_CHANNEL,
            "802-11-wireless.powersave",
            "2",
            "802-11-wireless-security.key-mgmt",
            "none",
            "ipv4.method",
            "shared",
            "ipv4.addresses",
            HOTSPOT_CIDR,
            "ipv6.method",
            "disabled",
        ]
    )


def start_hotspot() -> dict[str, Any]:
    if not has_nmcli():
        raise RuntimeError("NetworkManager (nmcli) is not installed")
    wait_for_networkmanager(20)

    ssid = hotspot_ssid()
    dev = wifi_device() or "wlan0"
    _prepare_radio(dev)

    # Scan while the radio is still a client. AP mode on a Pi usually cannot see other SSIDs.
    try:
        pre = scan_networks(rescan=True)
        log.info("Cached %s nearby network(s) before starting hotspot", len(pre))
    except Exception as e:
        log.warning("Pre-hotspot scan failed: %s", e)

    # Write captive DNS before bringing the AP up (dnsmasq-shared reads it on start).
    # Do not reload NetworkManager here.
    _write_dnsmasq_captive(reload_nm=False)

    with _lock:
        log.info("Starting open setup hotspot SSID=%s on %s", ssid, dev)
        if not _connection_exists(HOTSPOT_CONN):
            add = _nm(
                [
                    "nmcli",
                    "connection",
                    "add",
                    "type",
                    "wifi",
                    "ifname",
                    dev,
                    "con-name",
                    HOTSPOT_CONN,
                    "autoconnect",
                    "no",
                    "ssid",
                    ssid,
                ]
            )
            if add.returncode != 0:
                raise RuntimeError(add.stderr.strip() or "Failed to create hotspot connection")

        mod = _modify_hotspot_settings(ssid, dev)
        if mod.returncode != 0:
            # Older nmcli may reject powersave / channel. Retry a smaller set.
            log.warning("Full hotspot modify failed (%s); retrying essentials", (mod.stderr or "").strip())
            _nm(
                [
                    "nmcli",
                    "connection",
                    "modify",
                    HOTSPOT_CONN,
                    "802-11-wireless.mode",
                    "ap",
                    "802-11-wireless.band",
                    "bg",
                    "ipv4.method",
                    "shared",
                    "ipv4.addresses",
                    HOTSPOT_CIDR,
                    "ipv6.method",
                    "disabled",
                    "wifi-sec.key-mgmt",
                    "none",
                ]
            )

        # Open network: drop leftover WPA keys if a previous version set them.
        _nm(["nmcli", "connection", "modify", HOTSPOT_CONN, "remove", "wifi-sec"])
        _nm(
            [
                "nmcli",
                "connection",
                "modify",
                HOTSPOT_CONN,
                "wifi-sec.key-mgmt",
                "none",
            ]
        )

        # Leave any station association so the radio can become an AP.
        _nm(["nmcli", "device", "disconnect", dev], timeout=20)
        time.sleep(1)

        last_err = ""
        up = None
        for attempt in range(1, 4):
            up = _nm(["nmcli", "connection", "up", HOTSPOT_CONN], timeout=60)
            if up.returncode == 0:
                break
            last_err = (up.stderr or up.stdout or "Failed to start hotspot").strip()
            log.warning("Hotspot up attempt %s failed: %s", attempt, last_err)
            time.sleep(2 * attempt)
        if not up or up.returncode != 0:
            hint = ""
            err_l = last_err.lower()
            if "dnsmasq" in err_l or "dhcp" in err_l or "shared" in err_l:
                hint = (
                    " Install dnsmasq-base (not the dnsmasq service) so NetworkManager "
                    "can hand out 10.42.0.1/24 addresses."
                )
            raise RuntimeError((last_err or "Failed to start hotspot") + hint)

        enable_http80_redirect()
        ready = _wait_hotspot_ready(dev, timeout=18)
        if not ready:
            log.warning(
                "Hotspot connection is up but %s is not on %s yet (DHCP/shared may be missing)",
                HOTSPOT_IP,
                dev,
            )
        _invalidate_hotspot_cache()
        set_led_mode("hotspot")
        log.info("Hotspot up; join open SSID %s then open http://%s:8080/wifi", ssid, HOTSPOT_IP)
        return wifi_status()


def stop_hotspot() -> dict[str, Any]:
    with _lock:
        if has_nmcli():
            _nm(["nmcli", "connection", "down", HOTSPOT_CONN], timeout=20)
            # Keep the profile so the next start is faster and less flaky.
        _disable_captive_redirects()
        _invalidate_hotspot_cache()
        set_led_mode("idle")
        log.info("Setup hotspot stopped")
        return wifi_status()


def _wait_device_ready_for_station(dev: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = _nm(["nmcli", "-t", "-f", "DEVICE,STATE", "device", "status"])
        for line in r.stdout.splitlines():
            parts = line.split(":")
            if parts and parts[0] == dev:
                state = parts[1] if len(parts) > 1 else ""
                if "unavailable" in state:
                    _prepare_radio(dev)
                    break
                if state in {"disconnected", "connected", "connecting", "disconnected (externally)"}:
                    return
        time.sleep(0.5)


def _station_con_name(ssid: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", ssid).strip("-") or "home"
    return f"adhan-home-{safe}"[:43]


def _connect_station(dev: str, ssid: str, password: str | None, hidden: bool) -> subprocess.CompletedProcess:
    con = _station_con_name(ssid)
    if _connection_exists(con):
        _nm(["nmcli", "connection", "delete", con])

    add_cmd = [
        "nmcli",
        "connection",
        "add",
        "type",
        "wifi",
        "ifname",
        dev,
        "con-name",
        con,
        "ssid",
        ssid,
        "connection.autoconnect",
        "yes",
        "connection.autoconnect-priority",
        "100",
        "802-11-wireless.powersave",
        "2",
    ]
    if hidden:
        add_cmd += ["802-11-wireless.hidden", "yes"]
    add = _nm(add_cmd)
    if add.returncode != 0:
        return add

    if password:
        sec = _nm(
            [
                "nmcli",
                "connection",
                "modify",
                con,
                "wifi-sec.key-mgmt",
                "wpa-psk",
                "wifi-sec.psk",
                password,
            ]
        )
        if sec.returncode != 0:
            return sec
    else:
        _nm(["nmcli", "connection", "modify", con, "remove", "wifi-sec"])
        _nm(["nmcli", "connection", "modify", con, "wifi-sec.key-mgmt", "none"])

    up = _nm(["nmcli", "connection", "up", con], timeout=45)
    if up.returncode == 0:
        return up

    # Some home routers are WPA3-only; retry with SAE if PSK failed.
    if password and up.returncode != 0:
        sae = _nm(
            [
                "nmcli",
                "connection",
                "modify",
                con,
                "wifi-sec.key-mgmt",
                "sae",
                "wifi-sec.psk",
                password,
            ]
        )
        if sae.returncode == 0:
            up = _nm(["nmcli", "connection", "up", con], timeout=45)
            if up.returncode == 0:
                return up

    # Fallback: classic "device wifi connect" after a rescan.
    _nm(["nmcli", "device", "wifi", "rescan"])
    time.sleep(2)
    cmd = ["nmcli", "device", "wifi", "connect", ssid, "ifname", dev]
    if password:
        cmd += ["password", password]
    if hidden:
        cmd += ["hidden", "yes"]
    return _nm(cmd, timeout=90)


def _restore_hotspot_after_failure() -> None:
    for attempt in range(1, 4):
        try:
            start_hotspot()
            return
        except Exception as e:
            log.error("Failed to restore hotspot (attempt %s): %s", attempt, e)
            time.sleep(2 * attempt)


def connect_wifi(ssid: str, password: str | None = None, hidden: bool = False) -> dict[str, Any]:
    """Leave hotspot (if any) and join a home Wi-Fi network (blocking)."""
    if not has_nmcli():
        raise RuntimeError("NetworkManager (nmcli) is not installed")
    ssid = (ssid or "").strip()
    if not ssid:
        raise ValueError("SSID is required")
    if len(ssid) > 32:
        raise ValueError("SSID too long")

    with _lock:
        if _connect_state.get("busy") and _connect_state.get("phase") != "connecting":
            raise RuntimeError("A Wi-Fi connect is already in progress")
        _connect_state.update(
            {"busy": True, "phase": "connecting", "ssid": ssid, "error": None, "wifi": None}
        )

    hotspot_was_up = is_hotspot_active()
    previous_conn = None if hotspot_was_up else _active_station_connection()
    dev = wifi_device() or "wlan0"
    try:
        log.info("Connecting to Wi-Fi SSID=%s", ssid)
        wait_for_networkmanager(15)
        if is_hotspot_active():
            # Cache one last scan while AP is still up (usually empty; cache from start remains).
            try:
                scan_networks(rescan=False)
            except Exception:
                pass
            _nm(["nmcli", "connection", "down", HOTSPOT_CONN], timeout=20)
            _disable_captive_redirects()
            _invalidate_hotspot_cache()
            time.sleep(2)
            _wait_device_ready_for_station(dev)

        _prepare_radio(dev)

        last = None
        for attempt in range(1, 4):
            if attempt > 1:
                _nm(["nmcli", "device", "wifi", "rescan"])
                time.sleep(1.5 * attempt)
            last = _connect_station(dev, ssid, password, hidden)
            if last.returncode == 0:
                break
            log.warning(
                "Wi-Fi connect attempt %s failed: %s",
                attempt,
                (last.stderr or last.stdout or "").strip(),
            )

        if not last or last.returncode != 0:
            raw = (last.stderr or last.stdout or "Failed to connect").strip() if last else "Failed to connect"
            err = _friendly_nmcli_error(raw)
            log.error("Wi-Fi connect failed: %s", raw)
            if not (previous_conn and _bring_up_saved(previous_conn)):
                _restore_hotspot_after_failure()
            with _lock:
                _connect_state.update(
                    {"busy": False, "phase": "failed", "error": err, "wifi": wifi_status()}
                )
            raise RuntimeError(err)

        con = _station_con_name(ssid)
        _nm(["nmcli", "connection", "modify", con, "connection.autoconnect", "yes"])

        for _ in range(30):
            if has_default_route():
                break
            time.sleep(0.5)

        set_led_mode("online" if has_internet() else "idle")
        status = wifi_status()
        with _lock:
            _connect_state.update(
                {"busy": False, "phase": "succeeded", "error": None, "wifi": status}
            )
        log.info("Connected to %s (online=%s)", ssid, status["online"])
        return status
    except Exception:
        with _lock:
            if _connect_state.get("phase") == "connecting":
                _connect_state.update({"busy": False, "phase": "failed"})
        raise


def connect_wifi_async(ssid: str, password: str | None = None, hidden: bool = False) -> dict[str, Any]:
    """Start connect in a background thread; poll GET /api/wifi for progress."""
    ssid = (ssid or "").strip()
    if not ssid:
        raise ValueError("SSID is required")
    with _lock:
        if _connect_state.get("busy"):
            raise RuntimeError("A Wi-Fi connect is already in progress")
        _connect_state.update(
            {"busy": True, "phase": "connecting", "ssid": ssid, "error": None, "wifi": None}
        )

    def _job():
        try:
            # connect_wifi is already marked busy/connecting above.
            connect_wifi(ssid, password, hidden=hidden)
        except Exception as e:
            log.error("Async Wi-Fi connect error: %s", e)
            with _lock:
                _connect_state.update(
                    {
                        "busy": False,
                        "phase": "failed",
                        "error": str(e),
                    }
                )

    threading.Thread(target=_job, name="adhan-wifi-connect", daemon=True).start()
    return wifi_status()


# ---------------------------------------------------------------------------
# LED status (ACT LED on Raspberry Pi)
# ---------------------------------------------------------------------------

def _led_path() -> Path | None:
    for p in (
        Path("/sys/class/leds/ACT/brightness"),
        Path("/sys/class/leds/led0/brightness"),
    ):
        if p.exists():
            return p
    return None


def set_led_mode(mode: str) -> None:
    global _led_mode
    _led_mode = mode


def _led_write(on: bool) -> None:
    path = _led_path()
    if not path:
        return
    value = "1" if on else "0"
    try:
        path.write_text(value)
    except PermissionError:
        subprocess.run(
            _ensure_sudo_nmcli() + ["tee", str(path)],
            input=value + "\n",
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception:
        pass


def _led_loop() -> None:
    while not _led_stop.is_set():
        mode = _led_mode
        if mode == "hotspot":
            _led_write(True)
            if _led_stop.wait(0.7):
                break
            _led_write(False)
            if _led_stop.wait(0.7):
                break
        elif mode == "error":
            _led_write(True)
            if _led_stop.wait(0.15):
                break
            _led_write(False)
            if _led_stop.wait(0.15):
                break
        elif mode == "online":
            _led_write(True)
            _led_stop.wait(2.0)
        else:
            _led_write(False)
            _led_stop.wait(2.0)


def start_led_indicator() -> None:
    global _led_thread
    if _led_path() is None:
        return
    if _led_thread and _led_thread.is_alive():
        return
    _led_stop.clear()
    _led_thread = threading.Thread(target=_led_loop, name="adhan-led", daemon=True)
    _led_thread.start()


def stop_led_indicator() -> None:
    _led_stop.set()


# ---------------------------------------------------------------------------
# Boot watchdog: auto hotspot when offline
# ---------------------------------------------------------------------------

def ensure_connectivity_or_hotspot(wait_secs: int | None = None) -> dict[str, Any]:
    """If not on a station network after wait, start the setup hotspot."""
    from app.config import load_config

    cfg = load_config()
    if not cfg.get("wifi_hotspot_auto", True):
        return wifi_status()
    if not has_nmcli():
        log.warning("nmcli missing; cannot auto-start hotspot")
        return wifi_status()

    wait_for_networkmanager(25)
    saved = saved_wifi_connections()
    wait = wait_secs if wait_secs is not None else hotspot_wait_secs(cfg, len(saved))
    log.info(
        "Wi-Fi watchdog: waiting up to %ss for station connection (saved profiles=%s)",
        wait,
        len(saved),
    )
    deadline = time.time() + max(5, wait)
    while time.time() < deadline and not _watchdog_stop.is_set():
        if is_station_connected():
            set_led_mode("online" if has_internet() else "idle")
            log.info("Wi-Fi station connected (%s)", current_ssid())
            return wifi_status()
        if is_hotspot_active():
            set_led_mode("hotspot")
            return wifi_status()
        time.sleep(2)

    if is_station_connected():
        set_led_mode("online" if has_internet() else "idle")
        return wifi_status()
    if is_hotspot_active():
        set_led_mode("hotspot")
        return wifi_status()

    try:
        return start_hotspot()
    except Exception as e:
        set_led_mode("error")
        log.error("Auto-hotspot failed: %s", e)
        return wifi_status()


def start_wifi_watchdog() -> None:
    global _watchdog_thread
    if _watchdog_thread and _watchdog_thread.is_alive():
        return
    start_led_indicator()
    _watchdog_stop.clear()

    def _run_watchdog():
        try:
            ensure_connectivity_or_hotspot()
        except Exception as e:
            log.error("Wi-Fi watchdog error: %s", e)
        hotspot_idle_since: float | None = None
        while not _watchdog_stop.is_set():
            _watchdog_stop.wait(WATCHDOG_INTERVAL_SECS)
            if _watchdog_stop.is_set():
                break
            from app.config import load_config

            if not load_config().get("wifi_hotspot_auto", True):
                continue
            if is_hotspot_active():
                if _hotspot_has_clients() is not False:
                    hotspot_idle_since = None
                    continue
                now = time.monotonic()
                if hotspot_idle_since is None:
                    hotspot_idle_since = now
                elif now - hotspot_idle_since >= HOTSPOT_RETRY_SECS:
                    hotspot_idle_since = None
                    try:
                        retry_home_wifi()
                    except Exception as e:
                        log.error("Home Wi-Fi retry failed: %s", e)
                continue
            hotspot_idle_since = None
            if is_station_connected():
                set_led_mode("online" if has_internet() else "idle")
                continue
            log.warning("Lost Wi-Fi; starting setup hotspot")
            try:
                start_hotspot()
            except Exception as e:
                log.error("Hotspot restart failed: %s", e)
                set_led_mode("error")

    _watchdog_thread = threading.Thread(target=_run_watchdog, name="adhan-wifi-watchdog", daemon=True)
    _watchdog_thread.start()


def stop_wifi_watchdog() -> None:
    _watchdog_stop.set()
    stop_led_indicator()
