"""Local geocoding helper: Nominatim search via the device, timezone from coordinates.

The portal calls this API instead of talking to Nominatim from the browser.
That avoids CORS / User-Agent blocks and lets the Pi cache results.
Search needs internet. Timezone from lat/lon works offline.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any
import requests

from app import __version__

log = logging.getLogger("adhan.geocode")

NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = f"AdhanPlayer/{__version__} (local-first; https://github.com/basilrizwan/adhan-player)"
MIN_INTERVAL_SECS = 1.1
SEARCH_CACHE_TTL_SECS = 7 * 24 * 3600
MAX_RESULTS = 6

_lock = threading.RLock()
_last_request_at = 0.0
_tf = None
_tf_tried = False


def _cache_path():
    from app.config import CACHE_DIR

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / "geocode-cache.json"


def _load_cache() -> dict[str, Any]:
    path = _cache_path()
    if not path.exists():
        return {"search": {}, "reverse": {}}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {"search": {}, "reverse": {}}
        data.setdefault("search", {})
        data.setdefault("reverse", {})
        return data
    except Exception:
        return {"search": {}, "reverse": {}}


def _save_cache(data: dict[str, Any]) -> None:
    try:
        path = _cache_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.replace(path)
    except OSError as e:
        log.warning("Could not save geocode cache: %s", e)


def _rate_limit() -> None:
    global _last_request_at
    with _lock:
        wait = MIN_INTERVAL_SECS - (time.time() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.time()


def timezone_at(lat: float, lon: float) -> str | None:
    """IANA timezone for a point. Offline (bundled timezonefinder data)."""
    global _tf, _tf_tried
    if _tf is None and not _tf_tried:
        _tf_tried = True
        try:
            from timezonefinder import TimezoneFinder

            _tf = TimezoneFinder()
        except Exception as e:
            log.warning("timezonefinder unavailable: %s", e)
            _tf = None
    if _tf is None:
        return None
    try:
        tz = _tf.timezone_at(lng=float(lon), lat=float(lat))
        if not tz:
            closest = getattr(_tf, "closest_timezone_at", None)
            if callable(closest):
                tz = closest(lng=float(lon), lat=float(lat))
        return tz or None
    except Exception as e:
        log.warning("timezone lookup failed: %s", e)
        return None


def _short_name(item: dict[str, Any]) -> str:
    addr = item.get("address") or {}
    locality = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("hamlet")
        or addr.get("suburb")
        or addr.get("county")
    )
    parts: list[str] = []
    for val in (locality, addr.get("state"), addr.get("country")):
        if val and val not in parts:
            parts.append(val)
    if parts:
        return ", ".join(parts)
    name = (item.get("display_name") or "").strip()
    return name or "Unknown place"


def _to_result(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        lat = float(item.get("lat"))
        lon = float(item.get("lon"))
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    name = _short_name(item)
    return {
        "name": name,
        "display_name": (item.get("display_name") or name).strip(),
        "latitude": round(lat, 6),
        "longitude": round(lon, 6),
        "timezone": timezone_at(lat, lon),
    }


def _nominatim_get(url: str, params: dict[str, Any], timeout: float = 12.0) -> Any:
    _rate_limit()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "en",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        raise ConnectionError(str(e)) from e
    if resp.status_code == 429:
        raise ConnectionError("Location search is rate-limited. Wait a moment and try again.")
    if resp.status_code >= 400:
        raise ConnectionError(f"Location search failed (HTTP {resp.status_code}).")
    try:
        return resp.json()
    except ValueError as e:
        raise ConnectionError("Location search returned invalid JSON.") from e


def search_places(query: str, limit: int = MAX_RESULTS) -> dict[str, Any]:
    q = " ".join((query or "").split())
    if len(q) < 2:
        return {"ok": True, "offline": False, "query": q, "results": [], "error": None}

    key = q.lower()
    now = time.time()
    with _lock:
        cache = _load_cache()
        hit = cache.get("search", {}).get(key)
        if hit and now - float(hit.get("ts") or 0) < SEARCH_CACHE_TTL_SECS:
            results = hit.get("results") or []
            # Recompute timezone in case timezonefinder was added later
            for row in results:
                if not row.get("timezone"):
                    row["timezone"] = timezone_at(row["latitude"], row["longitude"])
            return {"ok": True, "offline": False, "query": q, "results": results, "error": None, "cached": True}

    try:
        raw = _nominatim_get(
            NOMINATIM_SEARCH,
            {
                "q": q,
                "format": "json",
                "addressdetails": 1,
                "limit": max(1, min(int(limit), 10)),
            },
        )
    except ConnectionError as e:
        return {
            "ok": False,
            "offline": True,
            "query": q,
            "results": [],
            "error": (
                "Location search needs internet. "
                "Enter latitude, longitude, and timezone manually, or try again when online."
            ),
            "detail": str(e),
        }

    results: list[dict[str, Any]] = []
    seen: set[tuple[float, float]] = set()
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            row = _to_result(item)
            if not row:
                continue
            coord = (row["latitude"], row["longitude"])
            if coord in seen:
                continue
            seen.add(coord)
            results.append(row)

    with _lock:
        cache = _load_cache()
        cache.setdefault("search", {})[key] = {"ts": now, "results": results}
        _save_cache(cache)

    return {"ok": True, "offline": False, "query": q, "results": results, "error": None, "cached": False}


def reverse_place(lat: float, lon: float) -> dict[str, Any]:
    tz = timezone_at(lat, lon)
    key = f"{round(float(lat), 4)},{round(float(lon), 4)}"
    now = time.time()
    with _lock:
        cache = _load_cache()
        hit = cache.get("reverse", {}).get(key)
        if hit and now - float(hit.get("ts") or 0) < SEARCH_CACHE_TTL_SECS:
            row = dict(hit.get("result") or {})
            if tz:
                row["timezone"] = tz
            return {"ok": True, "offline": False, "error": None, **row, "cached": True}

    try:
        raw = _nominatim_get(
            NOMINATIM_REVERSE,
            {
                "lat": lat,
                "lon": lon,
                "format": "json",
                "addressdetails": 1,
                "zoom": 12,
            },
        )
    except ConnectionError as e:
        return {
            "ok": bool(tz),
            "offline": True,
            "name": None,
            "display_name": None,
            "latitude": round(float(lat), 6),
            "longitude": round(float(lon), 6),
            "timezone": tz,
            "error": None if tz else str(e),
            "detail": str(e),
        }

    row = _to_result(raw) if isinstance(raw, dict) else None
    if not row:
        row = {
            "name": None,
            "display_name": None,
            "latitude": round(float(lat), 6),
            "longitude": round(float(lon), 6),
            "timezone": tz,
        }
    elif tz:
        row["timezone"] = tz

    with _lock:
        cache = _load_cache()
        cache.setdefault("reverse", {})[key] = {"ts": now, "result": row}
        _save_cache(cache)

    return {"ok": True, "offline": False, "error": None, **row, "cached": False}

