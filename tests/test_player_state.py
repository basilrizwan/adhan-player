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


def _run_scheduler(monkeypatch, configs, schedules, on_play):
    """Drive the real scheduler_loop with fake config/schedule; on_play records and may stop it."""
    import threading

    state = {"i": 0}
    monkeypatch.setattr(player, "load_config", lambda: configs[min(state["i"], len(configs) - 1)])
    monkeypatch.setattr(
        player, "build_full_schedule", lambda cfg: schedules[min(state["i"], len(schedules) - 1)]
    )
    monkeypatch.setattr(player, "get_today_times", lambda cfg: {})

    def fake_play_adhan(name, cfg):
        on_play(name)
        state["i"] += 1

    monkeypatch.setattr(player, "play_adhan", fake_play_adhan)
    player._shutdown.clear()
    player._reschedule.clear()
    t = threading.Thread(target=player.scheduler_loop, daemon=True)
    t.start()
    t.join(timeout=10)
    alive = t.is_alive()
    player._shutdown.set()
    t.join(timeout=5)
    player._shutdown.clear()
    assert not alive, "scheduler did not stop"


def _cfg(tz):
    return {
        "latitude": 0,
        "longitude": 0,
        "timezone": tz,
        "method": 2,
        "enabled_prayers": ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"],
        "play_on_boot": False,
        "sleep_enabled": False,
    }


def test_timezone_change_after_maghrib_does_not_replay(monkeypatch, isolated_played_prayers):
    houston, la = _cfg("America/Chicago"), _cfg("America/Los_Angeles")
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    # Houston Maghrib is due first; after it plays the location flips to San Ramon,
    # whose Maghrib (same local date) is later. Only Isha should follow.
    schedules = [
        [("Maghrib", now + timedelta(seconds=0.3))],
        [("Maghrib", now + timedelta(seconds=0.8)), ("Isha", now + timedelta(seconds=1.3))],
    ]
    played = []

    def on_play(name):
        played.append(name)
        if name == "Isha":
            player._shutdown.set()

    _run_scheduler(monkeypatch, [houston, la], schedules, on_play)
    assert played == ["Maghrib", "Isha"]


def test_restart_after_prayer_does_not_replay(monkeypatch, isolated_played_prayers):
    cfg = _cfg("America/Los_Angeles")
    tz = ZoneInfo("America/Los_Angeles")
    played = []

    def stop_after(name):
        played.append(name)
        player._shutdown.set()

    now = datetime.now(tz)
    _run_scheduler(monkeypatch, [cfg], [[("Asr", now + timedelta(seconds=0.3))]], stop_after)
    assert played == ["Asr"]
    assert isolated_played_prayers.exists()

    # Fresh process: only the on-disk record remains, and Asr is (again) in the future.
    now = datetime.now(tz)
    schedule = [("Asr", now + timedelta(seconds=0.3)), ("Maghrib", now + timedelta(seconds=0.8))]
    _run_scheduler(monkeypatch, [cfg], [schedule], stop_after)
    assert played == ["Asr", "Maghrib"]


def test_settings_change_during_playback_is_logged(monkeypatch, caplog):
    cfg = _cfg("America/Los_Angeles")
    now = datetime.now(ZoneInfo("America/Los_Angeles"))

    def change_settings_while_playing(name):
        player._reschedule.set()
        player._shutdown.set()

    with caplog.at_level("INFO", logger="adhan.player"):
        _run_scheduler(
            monkeypatch, [cfg], [[("Dhuhr", now + timedelta(seconds=0.3))]], change_settings_while_playing
        )
    assert "Settings changed during playback" in caplog.text


def test_played_record_prunes_old_days(isolated_played_prayers):
    player.mark_played("Fajr", date(2026, 10, 1))
    player.mark_played("Isha", date(2026, 10, 17))
    assert player.was_played("Isha", date(2026, 10, 17))
    assert not player.was_played("Isha", date(2026, 10, 16))
    assert not player.was_played("Fajr", date(2026, 10, 1))
