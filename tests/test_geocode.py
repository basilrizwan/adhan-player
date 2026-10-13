from app.geocode import _short_name, _to_result, search_places


NOMINATIM_ITEM = {
    "display_name": "San Ramon, Contra Costa County, California, United States",
    "lat": "37.7799273",
    "lon": "-121.9780151",
    "address": {
        "city": "San Ramon",
        "county": "Contra Costa County",
        "state": "California",
        "country": "United States",
    },
}


def test_short_name_from_address():
    assert _short_name(NOMINATIM_ITEM) == "San Ramon, California, United States"


def test_to_result_parses_coords(monkeypatch):
    monkeypatch.setattr("app.geocode.timezone_at", lambda lat, lon: "America/Los_Angeles")
    row = _to_result(NOMINATIM_ITEM)
    assert row["latitude"] == 37.779927
    assert row["longitude"] == -121.978015
    assert row["timezone"] == "America/Los_Angeles"
    assert "San Ramon" in row["name"]


def test_to_result_rejects_bad_coords():
    assert _to_result({"lat": "999", "lon": "0"}) is None
    assert _to_result({"lat": "x", "lon": "y"}) is None


def test_search_uses_cache(tmp_config, monkeypatch):
    monkeypatch.setattr("app.geocode.timezone_at", lambda lat, lon: "America/Los_Angeles")

    called = {"n": 0}

    def fake_get(url, params):
        called["n"] += 1
        return [NOMINATIM_ITEM]

    monkeypatch.setattr("app.geocode._nominatim_get", fake_get)
    first = search_places("San Ramon")
    second = search_places("San Ramon")
    assert first["ok"] is True
    assert first["results"][0]["name"].startswith("San Ramon")
    assert second["cached"] is True
    assert called["n"] == 1


def test_search_offline(monkeypatch):
    def boom(url, params):
        raise ConnectionError("Name or service not known")

    monkeypatch.setattr("app.geocode._nominatim_get", boom)
    out = search_places("Cairo")
    assert out["ok"] is False
    assert out["offline"] is True
    assert out["results"] == []
    assert "internet" in (out["error"] or "").lower()


def test_search_ignores_tiny_query():
    out = search_places("a")
    assert out["results"] == []
    assert out["ok"] is True


def test_timezone_known_point():
    import pytest

    try:
        import timezonefinder  # noqa: F401
    except Exception:
        pytest.skip("timezonefinder not installed")
    from app.geocode import timezone_at

    tz = timezone_at(37.78, -122.42)
    assert tz == "America/Los_Angeles"
