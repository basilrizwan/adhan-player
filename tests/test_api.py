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


def test_patch_rejects_bad_timezone(tmp_config):
    client = TestClient(app)
    res = client.patch("/api/config", json={"timezone": "Not/AZone"})
    assert res.status_code == 422


def test_patch_rejects_unknown_method(tmp_config):
    client = TestClient(app)
    res = client.patch("/api/config", json={"method": 99})
    assert res.status_code == 422


def test_patch_rejects_out_of_range_coords(tmp_config):
    client = TestClient(app)
    res = client.patch("/api/config", json={"latitude": 200})
    assert res.status_code == 422


def test_patch_boot_sound_maps_file(tmp_config):
    client = TestClient(app)
    res = client.patch("/api/config", json={"boot_sound": "bell"})
    assert res.status_code == 200
    body = res.json()
    assert body["boot_sound"] == "bell"
    assert body["boot_audio_file"].endswith("boot-bell.mp3")
    assert body["play_on_boot"] is True
    off = client.patch("/api/config", json={"boot_sound": "off"})
    assert off.json()["play_on_boot"] is False


def test_patch_reschedules(tmp_config, monkeypatch):
    called = {"n": 0}

    def fake_refresh(cfg=None):
        called["n"] += 1
        return []

    monkeypatch.setattr("app.api.refresh_schedule", fake_refresh)
    client = TestClient(app)
    res = client.patch("/api/config", json={"location_name": "Austin", "method": 2})
    assert res.status_code == 200
    assert called["n"] == 1


def test_mute_until_has_timezone(tmp_config):
    client = TestClient(app)
    res = client.post("/api/mute", json={"minutes": 15})
    assert res.status_code == 200
    until = res.json()["state"]["mute_until"]
    assert until
    assert until.endswith("Z") or "+" in until or until.count("-") >= 3
    assert res.json()["state"]["muted"] is True


def test_boot_picker_is_in_portal():
    from pathlib import Path

    html = Path("web/index.html").read_text()
    js = Path("web/assets/app.js").read_text()
    assert 'id="bootSound"' in html
    assert "audio/boot-${sound}.mp3" in js
    assert 'id="kahfMissing"' in html
    assert 'id="hotspotAuto"' in html
    assert "isSecureContext" in js


def test_concurrent_config_saves(tmp_config):
    from concurrent.futures import ThreadPoolExecutor

    client = TestClient(app)

    def save(i: int):
        return client.patch("/api/config", json={"volume": 50 + (i % 40)})

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(save, range(24)))
    assert all(r.status_code == 200 for r in results)


def test_audio_upload_writes_kahf(tmp_config, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.BASE_DIR", tmp_path)
    client = TestClient(app)
    data = b"ID3" + b"\x00" * 5000
    res = client.post(
        "/api/audio/upload",
        data={"target": "kahf"},
        files={"file": ("kahf.mp3", data, "audio/mpeg")},
    )
    assert res.status_code == 200, res.text
    assert res.json()["bytes"] == len(data)
    assert (tmp_path / "audio" / "kahf.mp3").read_bytes() == data
    assert not list((tmp_path / "audio").glob(".*.upload"))


def test_audio_upload_rejects_unknown_target_and_non_mp3(tmp_config, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.BASE_DIR", tmp_path)
    client = TestClient(app)
    res = client.post(
        "/api/audio/upload",
        data={"target": "../config.json"},
        files={"file": ("x.mp3", b"ID3data", "audio/mpeg")},
    )
    assert res.status_code == 400
    res = client.post(
        "/api/audio/upload",
        data={"target": "kahf"},
        files={"file": ("x.mp3", b"<html>not audio", "audio/mpeg")},
    )
    assert res.status_code == 400
    assert not (tmp_path / "audio" / "kahf.mp3").exists()
