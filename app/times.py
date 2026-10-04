"""Prayer-time calculation — offline via adhanpy, optional Aladhan refresh."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from app.config import CACHE_DIR, PRAYER_NAMES

log = logging.getLogger("adhan.times")

API_BASE = "http://api.aladhan.com/v1"

# Map our config method ints (Aladhan-style) to adhanpy CalculationMethod names
METHOD_TO_ADHANPY = {
    1: "KARACHI",
    2: "NORTH_AMERICA",  # ISNA
    3: "MUSLIM_WORLD_LEAGUE",
    4: "UMM_AL_QURA",
    5: "EGYPTIAN",
    7: "TEHRAN",
    15: "MOON_SIGHTING_COMMITTEE",
}


def _cache_path(year: int):
    return CACHE_DIR / f"prayer_times_{year}.json"


def load_cache(year: int) -> dict:
    path = _cache_path(year)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_cache(year: int, data: dict) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    path = _cache_path(year)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _tz(config: dict[str, Any]) -> ZoneInfo:
    try:
        return ZoneInfo(config.get("timezone") or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _adhanpy_method(method: int):
    from adhanpy.calculation.CalculationMethod import CalculationMethod

    name = METHOD_TO_ADHANPY.get(method, "NORTH_AMERICA")
    return getattr(CalculationMethod, name, CalculationMethod.NORTH_AMERICA)


def compute_day_offline(target: date, config: dict[str, Any]) -> dict[str, str] | None:
    """Compute prayer times locally with adhanpy."""
    try:
        from adhanpy.PrayerTimes import PrayerTimes
        from adhanpy.calculation.CalculationParameters import CalculationParameters
        from adhanpy.calculation.Madhab import Madhab

        lat = float(config["latitude"])
        lon = float(config["longitude"])
        tz = _tz(config)
        dt = datetime(target.year, target.month, target.day, 12, 0, tzinfo=tz)
        method = _adhanpy_method(int(config.get("method", 2)))
        params = CalculationParameters(method=method)
        params.madhab = Madhab.HANAFI if int(config.get("school", 0)) == 1 else Madhab.SHAFI
        pt = PrayerTimes((lat, lon), dt, calculation_parameters=params, time_zone=tz)

        mapping = {
            "Fajr": pt.fajr,
            "Dhuhr": pt.dhuhr,
            "Asr": pt.asr,
            "Maghrib": pt.maghrib,
            "Isha": pt.isha,
        }
        return {name: t.astimezone(tz).strftime("%H:%M") for name, t in mapping.items()}
    except Exception as e:
        log.warning("Offline prayer calculation failed: %s", e)
        return None


def fetch_day_aladhan(target: date, config: dict[str, Any]) -> dict[str, str] | None:
    timestamp = int(datetime.combine(target, datetime.min.time()).timestamp())
    try:
        resp = requests.get(
            f"{API_BASE}/timings/{timestamp}",
            params={
                "latitude": config["latitude"],
                "longitude": config["longitude"],
                "method": config["method"],
                "school": config.get("school", 0),
                "timezonestring": config.get("timezone") or "UTC",
            },
            timeout=15,
        )
        resp.raise_for_status()
        timings = resp.json()["data"]["timings"]
        return {name: timings[name].split(" ")[0] for name in PRAYER_NAMES}
    except Exception as e:
        log.warning("Aladhan fetch failed for %s: %s", target, e)
        return None


def get_day_times(target: date, config: dict[str, Any]) -> dict[str, str] | None:
    """Get times for a day: offline → cache → optional Aladhan."""
    year = target.year
    key = target.strftime("%Y-%m-%d")
    cache = load_cache(year)

    use_offline = config.get("use_offline_times", True)
    allow_api = config.get("aladhan_refresh", True)

    if use_offline:
        offline = compute_day_offline(target, config)
        if offline:
            if cache.get(key) != offline:
                cache[key] = offline
                save_cache(year, cache)
            return offline

    if key in cache:
        return cache[key]

    if allow_api:
        online = fetch_day_aladhan(target, config)
        if online:
            cache[key] = online
            save_cache(year, cache)
            return online

    return cache.get(key)


def get_today_times(config: dict[str, Any]) -> dict[str, str] | None:
    return get_day_times(date.today(), config)


def midnight_refresh(config: dict[str, Any]) -> None:
    tomorrow = date.today() + timedelta(days=1)
    get_day_times(tomorrow, config)


def check_clock_health() -> tuple[bool, str | None]:
    """Pi has no RTC — flag obviously wrong clocks."""
    now = datetime.now()
    if now.year < 2025:
        return False, "System clock looks wrong (before 2025). Check NTP / internet time sync."
    if now.year > 2100:
        return False, "System clock looks wrong (far future)."
    return True, None
