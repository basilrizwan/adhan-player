from datetime import date
from concurrent.futures import ThreadPoolExecutor

from app import times
from app.config import CALC_METHODS


SAN_RAMON = {
    "latitude": 37.7799,
    "longitude": -121.9780,
    "timezone": "America/Los_Angeles",
    "method": 2,
    "school": 1,
    "use_offline_times": True,
    "aladhan_refresh": False,
}


def test_cache_key_includes_location_method_school_tz():
    day = date(2026, 6, 15)
    a = times._cache_key(day, SAN_RAMON)
    b = times._cache_key(day, {**SAN_RAMON, "method": 7})
    c = times._cache_key(day, {**SAN_RAMON, "school": 0})
    d = times._cache_key(day, {**SAN_RAMON, "timezone": "America/Chicago"})
    e = times._cache_key(day, {**SAN_RAMON, "latitude": 30.2672})
    assert a != b
    assert a != c
    assert a != d
    assert a != e
    assert a.startswith("2026-06-15|")


def test_tehran_and_jafari_are_not_isna(tmp_config):
    day = date(2026, 6, 15)
    isna = times.compute_day_offline(day, SAN_RAMON)
    tehran = times.compute_day_offline(day, {**SAN_RAMON, "method": 7})
    jafari = times.compute_day_offline(day, {**SAN_RAMON, "method": 0})
    assert isna and tehran and jafari
    assert tehran["Fajr"] != isna["Fajr"]
    assert jafari["Maghrib"] != isna["Maghrib"]
    assert jafari["Maghrib"] > isna["Maghrib"]


def test_all_configured_methods_compute_offline():
    day = date(2026, 3, 20)
    missing = []
    for method in CALC_METHODS:
        times_for = times.compute_day_offline(day, {**SAN_RAMON, "method": method, "school": 0})
        if not times_for or set(times_for) != {"Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"}:
            missing.append(method)
    assert missing == []


def test_local_now_uses_configured_timezone():
    now = times.local_now({**SAN_RAMON, "timezone": "Pacific/Auckland"})
    assert now.tzinfo is not None
    assert getattr(now.tzinfo, "key", None) == "Pacific/Auckland"
    assert times.local_today({**SAN_RAMON, "timezone": "Pacific/Auckland"}) == now.date()


def test_cache_concurrent_writes_are_valid_json(tmp_config, tmp_path):
    def write(i: int) -> None:
        times.save_cache(2026, {f"k{i}": {"Fajr": "05:00"}})

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(24)))
    data = times.load_cache(2026)
    assert isinstance(data, dict)


def test_get_day_times_does_not_reuse_other_method(tmp_config):
    day = date(2026, 6, 15)
    isna = times.get_day_times(day, SAN_RAMON)
    tehran = times.get_day_times(day, {**SAN_RAMON, "method": 7})
    assert isna != tehran
    cache = times.load_cache(2026)
    assert times._cache_key(day, SAN_RAMON) in cache
    assert times._cache_key(day, {**SAN_RAMON, "method": 7}) in cache
