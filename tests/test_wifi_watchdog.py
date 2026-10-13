from pathlib import Path

from app.wifi import (
    HOTSPOT_CONN,
    _friendly_nmcli_error,
    retry_home_wifi,
    saved_wifi_connections,
)


def test_friendly_password_error():
    msg = _friendly_nmcli_error("Error: Secrets were required, but not provided.")
    assert "password" in msg.lower()


def test_friendly_ssid_not_found():
    msg = _friendly_nmcli_error("Error: No network with SSID 'Nope' found.")
    assert "find" in msg.lower()


def test_saved_connections_newest_first(monkeypatch):
    stdout = "\n".join(
        [
            f"{HOTSPOT_CONN}:802-11-wireless:9",
            "adhan-home-old:802-11-wireless:10",
            "adhan-home-new:802-11-wireless:50",
            "wired:802-3-ethernet:99",
        ]
    )

    class Result:
        def __init__(self):
            self.stdout = stdout

    monkeypatch.setattr("app.wifi.has_nmcli", lambda: True)
    monkeypatch.setattr("app.wifi._nm", lambda *a, **k: Result())
    assert saved_wifi_connections() == ["adhan-home-new", "adhan-home-old"]


def test_retry_home_wifi_skips_when_not_hotspot(monkeypatch):
    monkeypatch.setattr("app.wifi.saved_wifi_connections", lambda: ["adhan-home-Home"])
    monkeypatch.setattr("app.wifi.is_hotspot_active", lambda: False)
    assert retry_home_wifi() is False


def test_retry_home_wifi_rejoins_saved(monkeypatch):
    monkeypatch.setattr("app.wifi.saved_wifi_connections", lambda: ["adhan-home-Home"])
    monkeypatch.setattr("app.wifi.is_hotspot_active", lambda: True)
    monkeypatch.setattr("app.wifi._nm", lambda *a, **k: None)
    monkeypatch.setattr("app.wifi._disable_captive_redirects", lambda: None)
    monkeypatch.setattr("app.wifi._invalidate_hotspot_cache", lambda: None)
    monkeypatch.setattr("app.wifi.time.sleep", lambda _s: None)
    monkeypatch.setattr("app.wifi._bring_up_saved", lambda name: name == "adhan-home-Home")
    started = {"n": 0}
    monkeypatch.setattr("app.wifi.start_hotspot", lambda: started.__setitem__("n", started["n"] + 1))
    assert retry_home_wifi() is True
    assert started["n"] == 0


def test_wifi_page_keeps_change_flow():
    html = Path("web/wifi.html").read_text()
    assert "Change Wi-Fi" in html
    assert "function esc(" in html
    assert "function pickNetwork" in html
    assert "passwordField" in html
    assert "data-index" in html


def test_service_worker_skips_api_and_media():
    sw = Path("web/sw.js").read_text()
    assert 'event.request.method !== "GET"' in sw
    assert 'url.pathname.startsWith("/api/")' in sw
    assert 'url.pathname.startsWith("/media/")' in sw
    assert "adhan-shell-v5" in sw
