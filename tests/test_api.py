from fastapi.testclient import TestClient

from app.main import app


def test_geocode_search_endpoint(tmp_config, monkeypatch):
    monkeypatch.setattr(
        "app.api.search_places",
        lambda q, limit=6: {
            "ok": True,
            "offline": False,
            "query": q,
            "results": [
                {
                    "name": "Austin, Texas",
                    "display_name": "Austin, Texas, United States",
                    "latitude": 30.2672,
                    "longitude": -97.7431,
                    "timezone": "America/Chicago",
                }
            ],
            "error": None,
        },
    )
    client = TestClient(app)
    res = client.get("/api/geocode/search", params={"q": "Austin"})
    assert res.status_code == 200
    body = res.json()
    assert body["results"][0]["timezone"] == "America/Chicago"
    assert body["results"][0]["latitude"] == 30.2672


def test_geocode_search_short_query(tmp_config):
    client = TestClient(app)
    res = client.get("/api/geocode/search", params={"q": "a"})
    assert res.status_code == 200
    assert res.json()["results"] == []


def test_geocode_timezone_range(tmp_config):
    client = TestClient(app)
    res = client.get("/api/geocode/timezone", params={"lat": 200, "lon": 0})
    assert res.status_code == 400


def test_patch_audio_slots(tmp_config):
    client = TestClient(app)
    res = client.patch(
        "/api/config",
        json={
            "volume": 70,
            "fajr_volume": 40,
            "dua_volume": 60,
            "fajr_dua_id": "short-authentic",
            "fajr_dua_enabled": True,
            "fajr_dua_volume": 25,
            "prayer_overrides": {"Isha": {"volume": 90}},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["dua_volume"] == 60
    assert body["fajr_dua_id"] == "short-authentic"
    assert body["fajr_dua_audio_file"].endswith("short-authentic.mp3")
    assert body["fajr_dua_volume"] == 25
    assert body["prayer_overrides"]["Isha"]["volume"] == 90


def test_patch_rejects_bad_override_prayer(tmp_config):
    client = TestClient(app)
    res = client.patch("/api/config", json={"prayer_overrides": {"Brunch": {"volume": 1}}})
    assert res.status_code == 400


def test_audio_library_includes_slots(tmp_config):
    client = TestClient(app)
    res = client.get("/api/audio")
    assert res.status_code == 200
    body = res.json()
    assert "files" in body
    assert "slots" in body
    assert "regular_adhan" in body["slots"]
    assert "fajr_dua" in body["slots"]


def test_health(tmp_config):
    client = TestClient(app)
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["ok"] is True
