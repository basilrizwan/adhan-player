"""Config load/save and defaults for the Adhan Player."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
CACHE_DIR = BASE_DIR / "cache"
AUDIO_DIR = BASE_DIR / "audio"
WEB_DIR = BASE_DIR / "web"

PRAYER_NAMES = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]

CALC_METHODS = {
    0: "Jafari",
    1: "Karachi",
    2: "ISNA",
    3: "MWL",
    4: "Makkah",
    5: "Egypt",
    7: "Tehran",
    8: "Gulf",
    9: "Kuwait",
    10: "Qatar",
    11: "Singapore",
    12: "France",
    13: "Turkey",
    14: "Russia",
    15: "Moonsighting",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "setup_complete": False,
    "device_name": "Adhan Player",
    "location_name": "",
    "latitude": 37.7799,
    "longitude": -121.9780,
    "timezone": "America/Los_Angeles",
    "method": 2,
    "school": 1,
    "volume": 80,
    "fajr_volume": 50,
    "audio_file": "audio/adhan.mp3",
    "fajr_audio_file": "audio/fajr.mp3",
    "enabled_prayers": list(PRAYER_NAMES),
    "audio_output": "auto",
    "sleep_enabled": False,
    "play_on_boot": True,
    "boot_sound": "chime",
    "boot_audio_file": "audio/boot-chime.mp3",
    "boot_volume": 45,
    "dua_enabled": True,
    "dua_id": "short-authentic",
    "dua_audio_file": "audio/dua/short-authentic.mp3",
    "dua_delay_seconds": 2,
    "dua_include_promise": False,
    "kahf_enabled": False,
    "kahf_audio_file": "audio/kahf.mp3",
    "kahf_delay_minutes": 30,
    "kahf_weekday": 3,
    "kahf_length_minutes": 30,
    "kahf_isha_margin_minutes": 5,
    "use_offline_times": True,
    "aladhan_refresh": True,
    "wifi_hotspot_auto": True,
    "wifi_hotspot_password": "",
    "wifi_offline_wait_secs": 75,
    "auto_update": True,
    "update_on_boot": True,
    "update_at_midnight": True,
    "update_repo": "https://github.com/basilrizwan/adhan-player.git",
    "update_branch": "main",
}

_lock = threading.RLock()
_listeners: list = []


def migrate_config(data: dict[str, Any]) -> dict[str, Any]:
    """Fill missing keys from defaults without wiping user values."""
    merged = deepcopy(DEFAULT_CONFIG)
    merged.update(data or {})
    # Product default: sleep off so the portal stays reachable
    if "sleep_enabled" not in data:
        merged["sleep_enabled"] = False
    if "setup_complete" not in data and data.get("location_name"):
        merged["setup_complete"] = True
    return merged


def load_config() -> dict[str, Any]:
    with _lock:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                raw = json.load(f)
        else:
            raw = {}
        return migrate_config(raw)


def save_config(data: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        merged = migrate_config(data)
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(merged, f, indent=2)
            f.write("\n")
        tmp.replace(CONFIG_PATH)
        for cb in list(_listeners):
            try:
                cb(merged)
            except Exception:
                pass
        return merged


def update_config(patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        current = load_config()
        current.update({k: v for k, v in patch.items() if v is not None})
        return save_config(current)


def on_config_change(callback) -> None:
    _listeners.append(callback)


def public_config(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return config safe for the API (no secrets — currently none)."""
    return deepcopy(cfg or load_config())
