from app.audio_slots import migrate_audio_slots, profile_for, slots_summary
from app.config import DEFAULT_CONFIG, migrate_config


def test_migrate_inherits_single_volume_and_dua():
    original = {
        "volume": 75,
        "fajr_volume": 40,
        "dua_id": "short-authentic",
        "dua_enabled": True,
        "dua_audio_file": "audio/dua/short-authentic.mp3",
        "audio_file": "audio/adhan.mp3",
        "fajr_audio_file": "audio/fajr.mp3",
    }
    merged = migrate_config(original)
    assert merged["dua_volume"] == 75
    assert merged["fajr_dua_id"] == "short-authentic"
    assert merged["fajr_dua_enabled"] is True
    assert merged["fajr_dua_volume"] == 40
    assert merged["prayer_overrides"] == {}


def test_migrate_keeps_explicit_new_slots():
    original = {
        "volume": 80,
        "fajr_volume": 50,
        "dua_id": "from-fajr",
        "dua_volume": 30,
        "fajr_dua_id": "slow-teach",
        "fajr_dua_enabled": False,
        "fajr_dua_volume": 10,
        "prayer_overrides": {"Maghrib": {"volume": 99}},
    }
    merged = migrate_config(original)
    assert merged["dua_volume"] == 30
    assert merged["fajr_dua_id"] == "slow-teach"
    assert merged["fajr_dua_enabled"] is False
    assert merged["fajr_dua_volume"] == 10
    assert merged["prayer_overrides"]["Maghrib"]["volume"] == 99


def test_profile_fajr_vs_regular():
    cfg = migrate_config(
        {
            "volume": 80,
            "fajr_volume": 40,
            "audio_file": "audio/adhan.mp3",
            "fajr_audio_file": "audio/fajr.mp3",
            "dua_id": "short-authentic",
            "fajr_dua_id": "from-fajr",
            "dua_volume": 70,
            "fajr_dua_volume": 35,
            "dua_enabled": True,
            "fajr_dua_enabled": True,
        }
    )
    fajr = profile_for("Fajr", cfg)
    dhuhr = profile_for("Dhuhr", cfg)
    assert fajr["adhan_file"] == "audio/fajr.mp3"
    assert fajr["adhan_volume"] == 40
    assert fajr["dua_id"] == "from-fajr"
    assert fajr["dua_volume"] == 35
    assert dhuhr["adhan_file"] == "audio/adhan.mp3"
    assert dhuhr["adhan_volume"] == 80
    assert dhuhr["dua_id"] == "short-authentic"
    assert dhuhr["dua_volume"] == 70


def test_per_prayer_override_wins():
    cfg = migrate_config(
        {
            "volume": 80,
            "audio_file": "audio/adhan.mp3",
            "dua_id": "short-authentic",
            "prayer_overrides": {
                "Maghrib": {
                    "adhan_file": "audio/boot-chime.mp3",
                    "volume": 90,
                    "dua_id": "with-translation",
                    "dua_volume": 20,
                }
            },
        }
    )
    maghrib = profile_for("Maghrib", cfg)
    isha = profile_for("Isha", cfg)
    assert maghrib["adhan_file"] == "audio/boot-chime.mp3"
    assert maghrib["adhan_volume"] == 90
    assert maghrib["dua_id"] == "with-translation"
    assert maghrib["dua_volume"] == 20
    assert isha["adhan_file"] == "audio/adhan.mp3"
    assert isha["adhan_volume"] == 80


def test_kahf_has_no_dua():
    cfg = dict(DEFAULT_CONFIG)
    slot = profile_for("Kahf", cfg)
    assert slot["dua_enabled"] is False
    assert "kahf" in slot["adhan_file"]


def test_slots_summary_shape():
    summary = slots_summary(DEFAULT_CONFIG)
    assert set(summary) >= {"regular_adhan", "fajr_adhan", "regular_dua", "fajr_dua", "prayer_overrides"}


def test_migrate_audio_slots_ignores_unknown_prayer():
    merged = {"volume": 80, "fajr_volume": 50, "dua_id": "x", "dua_enabled": True}
    out = migrate_audio_slots(
        {"prayer_overrides": {"Nope": {"volume": 1}, "Fajr": {"volume": 3}}},
        merged,
    )
    assert "Nope" not in out["prayer_overrides"]
    assert out["prayer_overrides"]["Fajr"]["volume"] == 3
