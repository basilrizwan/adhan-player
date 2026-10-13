from fastapi.testclient import TestClient

from app.main import app


def test_captive_probe_serves_setup_page(monkeypatch):
    monkeypatch.setattr("app.wifi.hotspot_active_cached", lambda: True)
    client = TestClient(app, follow_redirects=False)
    res = client.get("/generate_204", headers={"host": "connectivitycheck.gstatic.com"})
    assert res.status_code == 200
    body = res.text.lower()
    assert "wifi" in body
    assert "success" not in body


def test_apple_hotspot_detect(monkeypatch):
    monkeypatch.setattr("app.wifi.hotspot_active_cached", lambda: True)
    client = TestClient(app, follow_redirects=False)
    res = client.get("/hotspot-detect.html", headers={"host": "captive.apple.com"})
    assert res.status_code == 200
    assert "Connect" in res.text or "Wi-Fi" in res.text or "wifi" in res.text.lower()


def test_api_not_intercepted(monkeypatch):
    monkeypatch.setattr("app.wifi.hotspot_active_cached", lambda: True)
    client = TestClient(app)
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_wifi_path_not_redirected(monkeypatch):
    monkeypatch.setattr("app.wifi.hotspot_active_cached", lambda: True)
    client = TestClient(app, follow_redirects=False)
    res = client.get("/wifi", headers={"host": "10.42.0.1:8080"})
    assert res.status_code == 200


def test_no_captive_when_hotspot_off(monkeypatch):
    monkeypatch.setattr("app.wifi.hotspot_active_cached", lambda: False)
    client = TestClient(app, follow_redirects=False)
    res = client.get("/generate_204")
    assert res.status_code == 404
