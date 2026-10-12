"""City search for the setup portal (needs internet on the device)."""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

import requests

from app import __version__

log = logging.getLogger("adhan.geocode")

OPEN_METEO_SEARCH = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = f"AdhanPlayer/{__version__} (+https://github.com/basilrizwan/adhan-player)"

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

_cache: dict[str, list[dict[str, Any]]] = {}
_cache_lock = threading.Lock()


class GeocodeUnavailable(RuntimeError):
    """The device could not reach any geocoding service."""


def _label(*parts: str | None) -> str:
    out: list[str] = []
    for p in parts:
        if p and p not in out:
            out.append(p)
    return ", ".join(out)


def _qualifier_matches(result: dict[str, Any], qualifiers: list[str]) -> bool:
    """"CA", "Texas", "Pakistan", "Punjab, Pakistan" → match region/country, not substrings."""
    fields = [str(result.get(k) or "").lower() for k in ("admin1", "admin2", "country")]
    code = str(result.get("country_code") or "").lower()
    words = {w for f in fields for w in f.replace("-", " ").split()}
    for q in qualifiers:
        q = q.strip().lower()
        if not q:
            continue
        if q == "uk":
            q = "gb"
        state = US_STATES.get(q.upper(), "").lower() if len(q) == 2 else ""
        if q == code or (state and state in fields):
            continue
        if any(f.startswith(q) for f in fields):
            continue
        if len(q) >= 3 and any(w.startswith(q) for w in words):
            continue
        return False
    return True


def _open_meteo(query: str, count: int) -> list[dict[str, Any]]:
    parts = [p.strip() for p in query.split(",")]
    name, qualifiers = parts[0], parts[1:]
    resp = requests.get(
        OPEN_METEO_SEARCH,
        params={"name": name, "count": 20 if qualifiers else count, "language": "en", "format": "json"},
        headers={"User-Agent": USER_AGENT},
        timeout=8,
    )
    resp.raise_for_status()
    rows = resp.json().get("results") or []
    if qualifiers:
        rows = [r for r in rows if _qualifier_matches(r, qualifiers)]
    out = []
    for r in rows[:count]:
        if r.get("latitude") is None or r.get("longitude") is None or not r.get("timezone"):
            continue
        out.append(
            {
                "name": r.get("name"),
                "label": _label(r.get("name"), r.get("admin1"), r.get("country")),
                "latitude": round(float(r["latitude"]), 5),
                "longitude": round(float(r["longitude"]), 5),
                "timezone": r["timezone"],
                "source": "open-meteo",
            }
        )
    return out


def _timezone_for(lat: float, lon: float) -> str | None:
    try:
        resp = requests.get(
            OPEN_METEO_FORECAST,
            params={"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=8,
        )
        resp.raise_for_status()
        return resp.json().get("timezone")
    except Exception as e:
        log.info("Timezone lookup failed for %s,%s: %s", lat, lon, e)
        return None


def _nominatim(query: str, count: int) -> list[dict[str, Any]]:
    resp = requests.get(
        NOMINATIM_SEARCH,
        params={"q": query, "format": "jsonv2", "limit": count, "addressdetails": 1},
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
        timeout=8,
    )
    resp.raise_for_status()
    out = []
    for r in resp.json()[:count]:
        lat, lon = round(float(r["lat"]), 5), round(float(r["lon"]), 5)
        tz = _timezone_for(lat, lon)
        if not tz:
            continue
        addr = r.get("address") or {}
        name = r.get("name") or addr.get("city") or addr.get("town") or addr.get("village")
        out.append(
            {
                "name": name or query,
                "label": _label(name, addr.get("state"), addr.get("country")) or r.get("display_name"),
                "latitude": lat,
                "longitude": lon,
                "timezone": tz,
                "source": "openstreetmap",
            }
        )
    return out


COORDS_RE = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def _reverse(lat: float, lon: float) -> list[dict[str, Any]]:
    tz = _timezone_for(lat, lon)
    if not tz:
        raise GeocodeUnavailable("Looking up coordinates needs the speaker to be online.")
    label = f"{lat:.4f}, {lon:.4f}"
    name = label
    try:
        resp = requests.get(
            NOMINATIM_REVERSE,
            params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 10},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
            timeout=8,
        )
        resp.raise_for_status()
        addr = resp.json().get("address") or {}
        place = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("county")
        if place:
            name = place
            label = _label(place, addr.get("state"), addr.get("country"))
    except Exception as e:
        log.info("Reverse geocoding failed for %s,%s: %s", lat, lon, e)
    return [
        {
            "name": name,
            "label": label,
            "latitude": round(lat, 5),
            "longitude": round(lon, 5),
            "timezone": tz,
            "source": "coordinates",
        }
    ]


def search_places(query: str, count: int = 6) -> list[dict[str, Any]]:
    """Return candidate places with coordinates and IANA timezone."""
    query = " ".join((query or "").split())
    if len(query) < 2:
        return []
    key = f"{query.lower()}|{count}"
    with _cache_lock:
        if key in _cache:
            return _cache[key]

    m = COORDS_RE.match(query)
    if m and abs(float(m.group(1))) <= 90 and abs(float(m.group(2))) <= 180:
        results = _reverse(float(m.group(1)), float(m.group(2)))
        with _cache_lock:
            _cache[key] = results
        return results

    errors = 0
    results: list[dict[str, Any]] = []
    try:
        results = _open_meteo(query, count)
    except Exception as e:
        errors += 1
        log.warning("Open-Meteo geocoding failed: %s", e)
    if not results:
        try:
            results = _nominatim(query, min(count, 4))
        except Exception as e:
            errors += 1
            log.warning("Nominatim geocoding failed: %s", e)
    if errors == 2:
        raise GeocodeUnavailable("City search needs the speaker to be online.")

    with _cache_lock:
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = results
    return results
