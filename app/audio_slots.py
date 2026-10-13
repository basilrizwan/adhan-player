"""Per-type audio slots: Fajr/regular adhan and dua, plus optional per-prayer overrides."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

AUDIO_SLOT_KEYS = (
    "dua_volume",
    "fajr_dua_id",
    "fajr_dua_enabled",
    "fajr_dua_volume",
    "fajr_dua_audio_file",
    "prayer_overrides",
)

OVERRIDE_KEYS = ("adhan_file", "volume", "dua_id", "dua_enabled", "dua_volume")


def _prayer_names() -> list[str]:
    from app.config import PRAYER_NAMES

    return PRAYER_NAMES


def migrate_audio_slots(original: dict[str, Any], merged: dict[str, Any]) -> dict[str, Any]:
    """Fill new audio slots from the previous single adhan/dua settings."""
    data = original or {}
    names = _prayer_names()
    volume = int(merged.get("volume", 80))
    fajr_volume = int(merged.get("fajr_volume", 50))
    dua_id = merged.get("dua_id")
    dua_enabled = bool(merged.get("dua_enabled", True))
    dua_file = merged.get("dua_audio_file")

    if "dua_volume" not in data or data.get("dua_volume") is None:
        merged["dua_volume"] = volume
    if "fajr_dua_id" not in data or not data.get("fajr_dua_id"):
        merged["fajr_dua_id"] = dua_id
    if "fajr_dua_enabled" not in data:
        merged["fajr_dua_enabled"] = dua_enabled
    if "fajr_dua_volume" not in data or data.get("fajr_dua_volume") is None:
        merged["fajr_dua_volume"] = fajr_volume
    if "fajr_dua_audio_file" not in data or not data.get("fajr_dua_audio_file"):
        merged["fajr_dua_audio_file"] = dua_file
    if "prayer_overrides" not in data or not isinstance(data.get("prayer_overrides"), dict):
        merged["prayer_overrides"] = {}
    else:
        cleaned: dict[str, Any] = {}
        for name, raw in data["prayer_overrides"].items():
            if name not in names or not isinstance(raw, dict):
                continue
            slot = {k: raw[k] for k in OVERRIDE_KEYS if k in raw and raw[k] is not None}
            if slot:
                cleaned[name] = slot
        merged["prayer_overrides"] = cleaned
    return merged


def _override(config: dict[str, Any], prayer_name: str) -> dict[str, Any]:
    raw = (config.get("prayer_overrides") or {}).get(prayer_name) or {}
    return raw if isinstance(raw, dict) else {}


def profile_for(prayer_name: str, config: dict[str, Any]) -> dict[str, Any]:
    """Resolved adhan + dua files and volumes for a prayer (or Test / Kahf)."""
    cfg = config or {}
    is_kahf = prayer_name == "Kahf"
    is_fajr = prayer_name == "Fajr"
    ov = {} if is_kahf else _override(cfg, prayer_name)

    if is_kahf:
        adhan_file = cfg.get("kahf_audio_file") or "audio/kahf.mp3"
        adhan_volume = int(cfg.get("volume", 80))
        dua_enabled = False
        dua_id = None
        dua_volume = adhan_volume
    else:
        if is_fajr:
            default_adhan = cfg.get("fajr_audio_file") or "audio/fajr.mp3"
        else:
            default_adhan = cfg.get("audio_file") or "audio/adhan.mp3"
        adhan_file = ov.get("adhan_file") or default_adhan
        if ov.get("volume") is not None:
            adhan_volume = int(ov["volume"])
        elif is_fajr:
            adhan_volume = int(cfg.get("fajr_volume", cfg.get("volume", 80)))
        else:
            adhan_volume = int(cfg.get("volume", 80))

        if ov.get("dua_enabled") is not None:
            dua_enabled = bool(ov["dua_enabled"])
        elif is_fajr and cfg.get("fajr_dua_enabled") is not None:
            dua_enabled = bool(cfg.get("fajr_dua_enabled"))
        else:
            dua_enabled = bool(cfg.get("dua_enabled", True))

        dua_id = ov.get("dua_id") or (
            cfg.get("fajr_dua_id") if is_fajr else None
        ) or cfg.get("dua_id")

        if ov.get("dua_volume") is not None:
            dua_volume = int(ov["dua_volume"])
        elif is_fajr and cfg.get("fajr_dua_volume") is not None:
            dua_volume = int(cfg.get("fajr_dua_volume"))
        elif cfg.get("dua_volume") is not None:
            dua_volume = int(cfg.get("dua_volume"))
        else:
            dua_volume = adhan_volume

    return {
        "prayer": prayer_name,
        "adhan_file": adhan_file,
        "adhan_volume": int(adhan_volume),
        "dua_enabled": bool(dua_enabled),
        "dua_id": dua_id,
        "dua_volume": int(dua_volume),
    }


def slots_summary(config: dict[str, Any]) -> dict[str, Any]:
    """Compact view of the four user-facing slots plus overrides."""
    cfg = config or {}
    fajr = profile_for("Fajr", cfg)
    regular = profile_for("Dhuhr", cfg)
    return {
        "regular_adhan": {"file": regular["adhan_file"], "volume": regular["adhan_volume"]},
        "fajr_adhan": {"file": fajr["adhan_file"], "volume": fajr["adhan_volume"]},
        "regular_dua": {
            "id": cfg.get("dua_id"),
            "enabled": bool(cfg.get("dua_enabled", True)),
            "volume": int(cfg.get("dua_volume", cfg.get("volume", 80))),
        },
        "fajr_dua": {
            "id": cfg.get("fajr_dua_id") or cfg.get("dua_id"),
            "enabled": bool(
                cfg["fajr_dua_enabled"] if cfg.get("fajr_dua_enabled") is not None else cfg.get("dua_enabled", True)
            ),
            "volume": int(cfg.get("fajr_dua_volume", cfg.get("fajr_volume", 50))),
        },
        "prayer_overrides": deepcopy(cfg.get("prayer_overrides") or {}),
    }
