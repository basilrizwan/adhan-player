"""Prayer-time calculation — offline via adhanpy, optional Aladhan refresh."""

from __future__ import annotations

import json
import logging
import threading
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
    9: "KUWAIT",
    10: "QATAR",
    11: "SINGAPORE",
    12: "UOIF",
    15: "MOON_SIGHTING_COMMITTEE",
}

# Aladhan methods adhanpy has no preset for: (fajr angle, isha angle, isha minutes after maghrib).
CUSTOM_METHOD_ANGLES = {
    0: (16.0, 14.0, 0),  # Jafari
    7: (17.7, 14.0, 0),  # Tehran
    8: (19.5, 0.0, 90),  # Gulf Region
    13: (18.0, 17.0, 0),  # Turkey (Diyanet)
    14: (16.0, 15.0, 0),  # Russia
}
# Fixed minute offsets Aladhan applies for some methods.
METHOD_OFFSETS = {
    13: {"dhuhr": 5, "asr": 4, "maghrib": 7},
}
# Methods whose Maghrib is when the sun is this many degrees below the horizon (not sunset).
MAGHRIB_ANGLES = {0: 4.0, 7: 4.5}


def local_now(config: dict[str, Any]) -> datetime:
    """Current time in the configured prayer timezone (the Pi's system TZ may differ)."""
    return datetime.now(_tz(config))


def local_today(config: dict[str, Any]) -> date:
    return local_now(config).date()


def _cache_key(target: date, config: dict[str, Any]) -> str:
    return "{}|{:.4f},{:.4f}|m{}|s{}|{}".format(
        target.strftime("%Y-%m-%d"),
        float(config["latitude"]),
        float(config["longitude"]),
        config.get("method", 2),
        config.get("school", 0),
        config.get("timezone") or "UTC",
    )


def _cache_path(year: int):
    return CACHE_DIR / f"prayer_times_{year}.json"


_cache_lock = threading.RLock()


def load_cache(year: int) -> dict:
    path = _cache_path(year)
    with _cache_lock:
        if not path.exists():
            return {}
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError) as e:
            log.warning("Ignoring unreadable prayer-time cache %s: %s", path.name, e)
            return {}


def save_cache(year: int, data: dict) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    path = _cache_path(year)
    with _cache_lock:
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)


def _tz(config: dict[str, Any]) -> ZoneInfo:
    try:
        return ZoneInfo(config.get("timezone") or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _calculation_params(method: int):
    from adhanpy.calculation.CalculationMethod import CalculationMethod
    from adhanpy.calculation.CalculationParameters import CalculationParameters
    from adhanpy.calculation.PrayerAdjustments import PrayerAdjustments

    if method in CUSTOM_METHOD_ANGLES:
        fajr, isha, interval = CUSTOM_METHOD_ANGLES[method]
        return CalculationParameters(
            fajr_angle=fajr,
            isha_angle=isha,
            isha_interval=interval,
            method_adjustments=PrayerAdjustments(**METHOD_OFFSETS.get(method, {})),
        )
    name = METHOD_TO_ADHANPY.get(method, "NORTH_AMERICA")
    return CalculationParameters(method=getattr(CalculationMethod, name))


def _maghrib_by_angle(pt, angle: float) -> datetime | None:
    """Evening time when the sun reaches `angle` degrees below the horizon (UTC)."""
    from adhanpy.util.CalendarUtil import rounded_minute
    from adhanpy.util.TimeComponents import TimeComponents

    comps = TimeComponents.from_float(pt._solar_time.hour_angle(-angle, True))
    if comps is None:
        return None
    return rounded_minute(comps.date_components(pt._date_components))


def compute_day_offline(target: date, config: dict[str, Any]) -> dict[str, str] | None:
    """Compute prayer times locally with adhanpy."""
    try:
        from adhanpy.PrayerTimes import PrayerTimes
        from adhanpy.calculation.Madhab import Madhab

        lat = float(config["latitude"])
        lon = float(config["longitude"])
        tz = _tz(config)
        dt = datetime(target.year, target.month, target.day, 12, 0, tzinfo=tz)
        method = int(config.get("method", 2))
        params = _calculation_params(method)
        params.madhab = Madhab.HANAFI if int(config.get("school", 0)) == 1 else Madhab.SHAFI
        pt = PrayerTimes((lat, lon), dt, calculation_parameters=params, time_zone=tz)

        maghrib = pt.maghrib
        if method in MAGHRIB_ANGLES:
            maghrib = _maghrib_by_angle(pt, MAGHRIB_ANGLES[method]) or maghrib

        mapping = {
            "Fajr": pt.fajr,
            "Dhuhr": pt.dhuhr,
            "Asr": pt.asr,
            "Maghrib": maghrib,
            "Isha": pt.isha,
        }
        return {name: t.astimezone(tz).strftime("%H:%M") for name, t in mapping.items()}
    except Exception as e:
        log.warning("Offline prayer calculation failed: %s", e)
        return None


def fetch_day_aladhan(target: date, config: dict[str, Any]) -> dict[str, str] | None:
    timestamp = int(datetime(target.year, target.month, target.day, 12, tzinfo=_tz(config)).timestamp())
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
    key = _cache_key(target, config)
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
    return get_day_times(local_today(config), config)


def midnight_refresh(config: dict[str, Any]) -> None:
    tomorrow = local_today(config) + timedelta(days=1)
    get_day_times(tomorrow, config)


def check_clock_health() -> tuple[bool, str | None]:
    """Pi has no RTC — flag obviously wrong clocks."""
    now = datetime.now()
    if now.year < 2025:
        return False, "System clock looks wrong (before 2025). Check NTP / internet time sync."
    if now.year > 2100:
        return False, "System clock looks wrong (far future)."
    return True, None
