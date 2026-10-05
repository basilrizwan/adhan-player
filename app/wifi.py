"""Wi‑Fi / hotspot helpers via NetworkManager (nmcli) for headless setup."""

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


def is_hotspot_active() -> bool:
    if not has_nmcli():
        return False
    r = _run(["nmcli", "-t", "-f", "NAME,DEVICE,TYPE", "connection", "show", "--active"])
    for line in r.stdout.splitlines():
        parts = line.split(":")
        if parts and parts[0] == HOTSPOT_CONN:
            return True
    return False


def wifi_device() -> str | None:
    if not has_nmcli():
        return None
    r = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"])
    for line in r.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[1] == "wifi":
            return parts[0]
    return "wlan0"


def current_ssid() -> str | None:
    if not has_nmcli():
        return None
    r = _run(["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi"])
    for line in r.stdout.splitlines():
        # ACTIVE:SSID — SSID may contain colons rarely; split once
        if line.startswith("yes:"):
            ssid = line[4:]
            return ssid or None
    # Fallback: connection name on wifi device
    r2 = _run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"])
    for line in r2.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[1] == "802-11-wireless" and parts[0] != HOTSPOT_CONN:
            return parts[0]
    return None


def has_default_route() -> bool:
    r = _run(["ip", "route", "show", "default"])
    return bool(r.stdout.strip())


def has_internet(timeout: float = 3.0) -> bool:
    """Cheap connectivity check — DNS or TCP to a public resolver."""
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
    """Connected to a normal Wi‑Fi AP (not our setup hotspot)."""
    if is_hotspot_active():
        return False
    ssid = current_ssid()
    if not ssid:
        return False
    return has_default_route()


def connect_progress() -> dict[str, Any]:
    with _lock:
        return dict(_connect_state)


def wifi_status() -> dict[str, Any]:
    hotspot = is_hotspot_active()
    ssid = current_ssid()
    online = (not hotspot) and has_internet()
    station = is_station_connected()
    return {
        "nmcli": has_nmcli(),
        "device": wifi_device(),
        "mode": "hotspot" if hotspot else ("station" if station else "offline"),
        "hotspot_active": hotspot,
        "hotspot_ssid": hotspot_ssid(),
        "hotspot_password": hotspot_password(),
        "hotspot_url": f"http://{HOTSPOT_IP}:8080/wifi",
        "ssid": None if hotspot else ssid,
        "has_route": has_default_route(),
        "online": online,
        "setup_needed": hotspot or not station,
        "captive": hotspot,
        "connect": connect_progress(),
    }


def _ensure_sudo_nmcli() -> list[str]:
    """Prefix with sudo when not root."""
    if os.geteuid() == 0:
        return []
    return ["sudo", "-n"]


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
        log.warning("Could not save Wi‑Fi scan cache: %s", e)


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
    cmd = _ensure_sudo_nmcli() + [
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
    r = _run(cmd, timeout=45)
    if r.returncode != 0:
        log.warning("nmcli wifi list failed: %s", (r.stderr or r.stdout).strip())
        return []
    return _parse_nmcli_wifi_stdout(r.stdout)


def _iw_scan() -> list[dict[str, Any]]:
    """Best-effort scan while AP mode is up (Pi firmware sometimes still reports BSS)."""
    dev = wifi_device() or "wlan0"
    r = _run(_ensure_sudo_nmcli() + ["iw", "dev", dev, "scan"], timeout=25)
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
    """List nearby Wi‑Fi networks. Uses a pre-hotspot cache because AP mode often cannot scan."""
    if not has_nmcli():
        return _load_scan_cache()

    with _lock:
        live: list[dict[str, Any]] = []
        hotspot = is_hotspot_active()
        # Rescan while AP is up usually returns empty and can wipe NM's list.
        live = _nmcli_wifi_list(rescan=rescan and not hotspot)
        if not live:
            live = _nmcli_wifi_list(rescan=False)
        if not live:
            live = _iw_scan()
        if live:
            _save_scan_cache(live)
            return live
        cached = _load_scan_cache()
        if cached:
            log.info("Using cached Wi‑Fi scan (%s networks) because live scan is empty", len(cached))
        return cached


def start_hotspot() -> dict[str, Any]:
    if not has_nmcli():
        raise RuntimeError("NetworkManager (nmcli) is not installed")

    ssid = hotspot_ssid()
    dev = wifi_device() or "wlan0"

    # Scan while the radio is still a client — AP mode on a Pi usually cannot see other SSIDs.
    try:
        pre = scan_networks(rescan=True)
        log.info("Cached %s nearby network(s) before starting hotspot", len(pre))
    except Exception as e:
        log.warning("Pre-hotspot scan failed: %s", e)

    with _lock:
        log.info("Starting open setup hotspot SSID=%s on %s", ssid, dev)
        _run(_ensure_sudo_nmcli() + ["nmcli", "connection", "delete", HOTSPOT_CONN])
        add = _run(
            _ensure_sudo_nmcli()
            + [
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

        mod = _run(
            _ensure_sudo_nmcli()
            + [
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
            ]
        )
        if mod.returncode != 0:
            raise RuntimeError(mod.stderr.strip() or "Failed to configure hotspot")

        # Open network — no WPA. Ignore failure if security keys were never set.
        _run(
            _ensure_sudo_nmcli()
            + [
                "nmcli",
                "connection",
                "modify",
                HOTSPOT_CONN,
                "remove",
                "wifi-sec",
            ]
        )
        _run(
            _ensure_sudo_nmcli()
            + [
                "nmcli",
                "connection",
                "modify",
                HOTSPOT_CONN,
                "wifi-sec.key-mgmt",
                "none",
            ]
        )

        up = _run(
            _ensure_sudo_nmcli() + ["nmcli", "connection", "up", HOTSPOT_CONN],
            timeout=60,
        )
        if up.returncode != 0:
            raise RuntimeError(up.stderr.strip() or "Failed to start hotspot")

        _enable_captive_redirects()
        _write_dnsmasq_captive()
        set_led_mode("hotspot")
        log.info("Hotspot up — join open SSID %s then open http://%s:8080/wifi", ssid, HOTSPOT_IP)
        return wifi_status()


def stop_hotspot() -> dict[str, Any]:
    with _lock:
        if has_nmcli():
            _run(_ensure_sudo_nmcli() + ["nmcli", "connection", "down", HOTSPOT_CONN])
            _run(_ensure_sudo_nmcli() + ["nmcli", "connection", "delete", HOTSPOT_CONN])
        _disable_captive_redirects()
        set_led_mode("idle")
        log.info("Setup hotspot stopped")
        return wifi_status()


def connect_wifi(ssid: str, password: str | None = None, hidden: bool = False) -> dict[str, Any]:
    """Leave hotspot (if any) and join a home Wi‑Fi network (blocking)."""
    if not has_nmcli():
        raise RuntimeError("NetworkManager (nmcli) is not installed")
    ssid = (ssid or "").strip()
    if not ssid:
        raise ValueError("SSID is required")
    if len(ssid) > 32:
        raise ValueError("SSID too long")

    with _lock:
        if _connect_state.get("busy"):
            raise RuntimeError("A Wi‑Fi connect is already in progress")
        _connect_state.update(
            {"busy": True, "phase": "connecting", "ssid": ssid, "error": None, "wifi": None}
        )

    try:
        log.info("Connecting to Wi‑Fi SSID=%s", ssid)
        # Tear down hotspot first so the radio can associate as station
        if is_hotspot_active():
            _run(_ensure_sudo_nmcli() + ["nmcli", "connection", "down", HOTSPOT_CONN])
            _run(_ensure_sudo_nmcli() + ["nmcli", "connection", "delete", HOTSPOT_CONN])
            _disable_captive_redirects()
            time.sleep(2)

        # Delete any previous connection with this name to avoid stale PSK
        _run(_ensure_sudo_nmcli() + ["nmcli", "connection", "delete", ssid])

        cmd = _ensure_sudo_nmcli() + [
            "nmcli",
            "device",
            "wifi",
            "connect",
            ssid,
        ]
        if password:
            cmd += ["password", password]
        if hidden:
            cmd += ["hidden", "yes"]
        r = _run(cmd, timeout=90)
        if r.returncode != 0:
            log.error("Wi‑Fi connect failed: %s", r.stderr.strip())
            try:
                start_hotspot()
            except Exception as e:
                log.error("Failed to restore hotspot after connect error: %s", e)
            err = (r.stderr or r.stdout or "Failed to connect").strip()
            with _lock:
                _connect_state.update(
                    {"busy": False, "phase": "failed", "error": err, "wifi": wifi_status()}
                )
            raise RuntimeError(err)

        _run(
            _ensure_sudo_nmcli()
            + ["nmcli", "connection", "modify", ssid, "connection.autoconnect", "yes"]
        )

        for _ in range(20):
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
            raise RuntimeError("A Wi‑Fi connect is already in progress")
        _connect_state.update(
            {"busy": True, "phase": "connecting", "ssid": ssid, "error": None, "wifi": None}
        )

    def _job():
        try:
            # Reset busy so connect_wifi can take ownership of the state machine
            with _lock:
                _connect_state["busy"] = False
            connect_wifi(ssid, password, hidden=hidden)
        except Exception as e:
            log.error("Async Wi‑Fi connect error: %s", e)
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


def _write_dnsmasq_captive() -> None:
    """Point all DNS names at the hotspot IP so captive browsers open our page."""
    conf_dir = Path("/etc/NetworkManager/dnsmasq-shared.d")
    conf = conf_dir / "adhan-captive.conf"
    try:
        if not conf_dir.is_dir():
            _run(_ensure_sudo_nmcli() + ["mkdir", "-p", str(conf_dir)])
        content = f"# Adhan Player captive DNS\naddress=/#/{HOTSPOT_IP}\n"
        # Write via tee for permissions
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
        _run(_ensure_sudo_nmcli() + ["systemctl", "reload", "NetworkManager"])
    except Exception as e:
        log.warning("dnsmasq captive setup failed: %s", e)


def _clear_dnsmasq_captive() -> None:
    conf = Path("/etc/NetworkManager/dnsmasq-shared.d/adhan-captive.conf")
    if conf.exists():
        _run(_ensure_sudo_nmcli() + ["rm", "-f", str(conf)])


def _enable_captive_redirects() -> None:
    """Redirect TCP/80 → 8080 on the AP so captive probes hit our portal."""
    # Clear then add (idempotent-ish)
    _disable_captive_redirects()
    for proto in ("iptables", "ip6tables"):
        _run(
            _ensure_sudo_nmcli()
            + [
                proto,
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
        )


def _disable_captive_redirects() -> None:
    for proto in ("iptables", "ip6tables"):
        # Delete all matching rules (loop a few times)
        for _ in range(4):
            r = _run(
                _ensure_sudo_nmcli()
                + [
                    proto,
                    "-t",
                    "nat",
                    "-D",
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
            )
            if r.returncode != 0:
                break
    _clear_dnsmasq_captive()


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
            # Slow blink: waiting for phone setup
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
# Boot watchdog — auto hotspot when offline
# ---------------------------------------------------------------------------

def ensure_connectivity_or_hotspot(wait_secs: int | None = None) -> dict[str, Any]:
    """If not on a station network after wait, start the setup hotspot."""
    from app.config import load_config

    cfg = load_config()
    if not cfg.get("wifi_hotspot_auto", True):
        return wifi_status()
    if not has_nmcli():
        log.warning("nmcli missing — cannot auto-start hotspot")
        return wifi_status()

    wait = wait_secs if wait_secs is not None else int(cfg.get("wifi_offline_wait_secs", 75))
    log.info("Wi‑Fi watchdog: waiting up to %ss for station connection", wait)
    deadline = time.time() + max(5, wait)
    while time.time() < deadline and not _watchdog_stop.is_set():
        if is_station_connected():
            set_led_mode("online" if has_internet() else "idle")
            log.info("Wi‑Fi station connected (%s)", current_ssid())
            return wifi_status()
        if is_hotspot_active():
            set_led_mode("hotspot")
            return wifi_status()
        time.sleep(3)

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
            log.error("Wi‑Fi watchdog error: %s", e)
        # Periodically re-check: if we lose station Wi‑Fi later, bring hotspot back
        while not _watchdog_stop.is_set():
            _watchdog_stop.wait(60)
            if _watchdog_stop.is_set():
                break
            from app.config import load_config

            if not load_config().get("wifi_hotspot_auto", True):
                continue
            if is_station_connected() or is_hotspot_active():
                if is_station_connected():
                    set_led_mode("online" if has_internet() else "idle")
                continue
            log.warning("Lost Wi‑Fi — starting setup hotspot")
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
