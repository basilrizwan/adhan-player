from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import player
from app.config import migrate_config
from app.state import get_state, is_muted, set_mute_until, update_state


def test_parse_time_is_timezone_aware():
    cfg = {"timezone": "America/Chicago"}
    dt = player.parse_time("18:30", date(2026, 6, 15), cfg)
    assert dt.tzinfo is not None
    assert dt.tzinfo.key == "America/Chicago"
    assert dt.hour == 18 and dt.minute == 30


def test_stop_skips_dua_after_adhan(monkeypatch):
    calls = []
    player._stop_generation = 0

    def fake_play_file(path, *, label="Audio", **kwargs):
        calls.append(label)
        player.stop_playback()
        return True

    monkeypatch.setattr(player, "play_file", fake_play_file)
    monkeypatch.setattr(player.time, "sleep", lambda _s: None)
    monkeypatch.setattr(player, "resolve_dua_path", lambda cfg, dua_id=None: "audio/dua/from-fajr.mp3")
    cfg = migrate_config(
        {
            "dua_enabled": True,
            "dua_id": "from-fajr",
            "audio_file": "audio/adhan.mp3",
            "volume": 80,
        }
    )
    player.play_adhan("Dhuhr", cfg)
    assert calls == ["Adhan for Dhuhr"]


def test_stop_during_dua_delay_skips_dua(monkeypatch):
    calls = []
    player._stop_generation = 0

    def fake_play_file(path, *, label="Audio", **kwargs):
        calls.append(label)
        return True

    def fake_sleep(_s):
        player.stop_playback()

    monkeypatch.setattr(player, "play_file", fake_play_file)
    monkeypatch.setattr(player.time, "sleep", fake_sleep)
    monkeypatch.setattr(player, "resolve_dua_path", lambda cfg, dua_id=None: "audio/dua/from-fajr.mp3")
    cfg = migrate_config({"dua_enabled": True, "dua_delay_seconds": 2, "audio_file": "audio/adhan.mp3"})
    player.play_adhan("Test", cfg)
    assert calls == ["Adhan for Test"]


def test_mute_until_is_timezone_aware():
    until = datetime.now(timezone.utc) + timedelta(minutes=30)
    state = set_mute_until(until)
    assert state["muted"] is True
    assert state["mute_until"]
    assert is_muted() is True
    set_mute_until(None)
    assert is_muted() is False


def test_find_next_prayer_uses_configured_tz():
    cfg = {"timezone": "America/Los_Angeles"}
    tz = ZoneInfo("America/Los_Angeles")
    now = datetime.now(tz)
    past = now - timedelta(minutes=5)
    future = now + timedelta(minutes=20)
    name, dt = player.find_next_prayer([("Dhuhr", past), ("Asr", future)], cfg)
    assert name == "Asr"
    assert dt == future


def test_refresh_schedule_publishes_today_times(tmp_config):
    update_state(today_times={}, schedule=[])
    cfg = migrate_config(
        {
            "latitude": 37.7799,
            "longitude": -121.9780,
            "timezone": "America/Los_Angeles",
            "method": 2,
            "school": 1,
            "enabled_prayers": ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"],
        }
    )
    schedule = player.refresh_schedule(cfg)
    state = get_state()
    assert state["today_times"]
    assert "Fajr" in state["today_times"]
    assert isinstance(schedule, list)
