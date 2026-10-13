from app.wifi import (
    _parse_nmcli_wifi_stdout,
    _station_con_name,
    hotspot_ssid,
    hotspot_wait_secs,
)


def test_parse_nmcli_wifi_list():
    stdout = "\n".join(
        [
            "HomeNet:80:WPA2:*",
            "Cafe:40:WPA2:",
            "Adhan-ABCD:99::",
            "HomeNet:10:WPA2:",
            "Colon\\:SSID:50:WPA3:",
        ]
    )
    nets = _parse_nmcli_wifi_stdout(stdout)
    ssids = [n["ssid"] for n in nets]
    assert "Adhan-ABCD" not in ssids
    assert ssids[0] == "HomeNet"
    assert nets[0]["in_use"] is True
    assert "Colon:SSID" in ssids


def test_hotspot_ssid_format():
    ssid = hotspot_ssid()
    assert ssid.startswith("Adhan-")
    assert len(ssid) >= 6


def test_hotspot_wait_short_when_no_saved():
    cfg = {"wifi_offline_wait_secs": 75}
    assert hotspot_wait_secs(cfg, 0) <= 12
    assert hotspot_wait_secs(cfg, 2) == 75


def test_station_con_name_is_stable_and_safe():
    assert _station_con_name("My WiFi") == "adhan-home-My-WiFi"
    assert " " not in _station_con_name("a b/c")
