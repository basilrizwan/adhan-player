"""REST API for the local Adhan Player portal and agents."""

from __future__ import annotations

import socket
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app import __version__
from app.audio_slots import OVERRIDE_KEYS, profile_for, slots_summary
from app.config import (
    AUDIO_DIR,
    BASE_DIR,
    BOOT_SOUNDS,
    CALC_METHODS,
    PRAYER_NAMES,
    load_config,
    public_config,
    update_config,
)
from app.dua import get_dua, list_duas
from app.geocode import reverse_place, search_places, timezone_at
from app.player import play_adhan, play_boot_sound, play_file, refresh_schedule, stop_playback
from app.state import get_state, request_skip, set_mute_until
from app.times import check_clock_health, get_today_times
from app.updater import apply_update_async, check_for_updates, status as update_status
from app.wifi import (
    connect_wifi_async,
    hotspot_ssid,
    scan_networks,
    start_hotspot,
    stop_hotspot,
    wifi_status,
)

router = APIRouter(prefix="/api")


class WifiConnectRequest(BaseModel):
    ssid: str = Field(min_length=1, max_length=32)
    password: Optional[str] = Field(default=None, max_length=128)
    hidden: bool = False


class ConfigPatch(BaseModel):
    setup_complete: Optional[bool] = None
    device_name: Optional[str] = Field(default=None, max_length=60)
    location_name: Optional[str] = Field(default=None, max_length=120)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    timezone: Optional[str] = None
    method: Optional[int] = None
    school: Optional[int] = Field(default=None, ge=0, le=1)
    volume: Optional[int] = Field(default=None, ge=0, le=100)
    fajr_volume: Optional[int] = Field(default=None, ge=0, le=100)
    audio_file: Optional[str] = None
    fajr_audio_file: Optional[str] = None
    enabled_prayers: Optional[list[str]] = None
    audio_output: Optional[str] = Field(default=None, pattern="^(auto|hdmi|headphone)$")
    sleep_enabled: Optional[bool] = None
    play_on_boot: Optional[bool] = None
    boot_sound: Optional[str] = None
    boot_audio_file: Optional[str] = None
    boot_volume: Optional[int] = Field(default=None, ge=0, le=100)
    dua_enabled: Optional[bool] = None
    dua_id: Optional[str] = None
    dua_audio_file: Optional[str] = None
    dua_volume: Optional[int] = Field(default=None, ge=0, le=100)
    dua_delay_seconds: Optional[float] = None
    dua_include_promise: Optional[bool] = None
    fajr_dua_enabled: Optional[bool] = None
    fajr_dua_id: Optional[str] = None
    fajr_dua_audio_file: Optional[str] = None
    fajr_dua_volume: Optional[int] = Field(default=None, ge=0, le=100)
    prayer_overrides: Optional[dict[str, dict[str, Any]]] = None
    kahf_enabled: Optional[bool] = None
    kahf_audio_file: Optional[str] = None
    kahf_delay_minutes: Optional[int] = None
    kahf_weekday: Optional[int] = None
    kahf_length_minutes: Optional[int] = None
    kahf_isha_margin_minutes: Optional[int] = None
    use_offline_times: Optional[bool] = None
    aladhan_refresh: Optional[bool] = None
    wifi_hotspot_auto: Optional[bool] = None
    wifi_hotspot_password: Optional[str] = None
    wifi_offline_wait_secs: Optional[int] = Field(default=None, ge=15, le=300)
    auto_update: Optional[bool] = None
    update_on_boot: Optional[bool] = None
    update_at_midnight: Optional[bool] = None
    update_repo: Optional[str] = None
    update_branch: Optional[str] = None

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        try:
            ZoneInfo(v)
        except Exception as e:
            raise ValueError(f"Unknown timezone: {v!r} (use an IANA name like America/Chicago)") from e
        return v

    @field_validator("method")
    @classmethod
    def _valid_method(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in CALC_METHODS:
            raise ValueError(f"Unknown calculation method: {v}")
        return v

    @field_validator("boot_sound")
    @classmethod
    def _valid_boot_sound(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in BOOT_SOUNDS and v != "off":
            raise ValueError(f"boot_sound must be one of: off, {', '.join(BOOT_SOUNDS)}")
        return v


class PlayRequest(BaseModel):
    kind: str = Field(
        description="adhan | fajr | dua | fajr_dua | kahf | file | test",
        default="test",
    )
    dua_id: Optional[str] = None
    prayer: Optional[str] = None
    path: Optional[str] = None
    volume: Optional[int] = Field(default=None, ge=0, le=100)


class MuteRequest(BaseModel):
    minutes: Optional[int] = Field(default=None, ge=1, le=24 * 60)
    until: Optional[str] = None
    clear: bool = False


class SkipRequest(BaseModel):
    prayer: Optional[str] = None


def _local_ips() -> list[str]:
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ":" in ip:
                continue
            if ip.startswith("127."):
                continue
            if ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    # UDP trick for primary outbound IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips:
            ips.insert(0, ip)
    except Exception:
        pass
    return ips


def _tail_log(lines: int = 40) -> list[str]:
    log_path = BASE_DIR / "cache" / "adhan.log"
    if not log_path.exists():
        return []
    try:
        text = log_path.read_text(errors="replace").splitlines()
        return text[-lines:]
    except Exception:
        return []


@router.get("/status")
def api_status() -> dict[str, Any]:
    cfg = load_config()
    st = get_state()
    clock_ok, clock_warning = check_clock_health()
    return {
        "version": __version__,
        "device_name": cfg.get("device_name", "Adhan Player"),
        "setup_complete": bool(cfg.get("setup_complete")),
        "location_name": cfg.get("location_name"),
        "latitude": cfg.get("latitude"),
        "longitude": cfg.get("longitude"),
        "timezone": cfg.get("timezone"),
        "ips": _local_ips(),
        "urls": [f"http://adhan.local"] + [f"http://{ip}" for ip in _local_ips()] + [f"http://adhan.local:8080"] + [f"http://{ip}:8080" for ip in _local_ips()],
        "clock_ok": clock_ok,
        "clock_warning": clock_warning,
        "state": st,
        "volume": cfg.get("volume"),
        "sleep_enabled": cfg.get("sleep_enabled", False),
        "dua_enabled": cfg.get("dua_enabled", True),
        "dua_id": cfg.get("dua_id"),
        "wifi": wifi_status(),
        "update": update_status(),
    }


@router.get("/config")
def api_get_config() -> dict[str, Any]:
    return public_config()


@router.patch("/config")
def api_patch_config(patch: ConfigPatch) -> dict[str, Any]:
    data = patch.model_dump(exclude_unset=True)
    if "dua_id" in data and data["dua_id"]:
        entry = get_dua(data["dua_id"])
        if not entry:
            raise HTTPException(400, f"Unknown dua_id: {data['dua_id']}")
        data["dua_audio_file"] = entry["file"]
        data["dua_include_promise"] = entry["variant"] == "with_promise"
    if "fajr_dua_id" in data and data["fajr_dua_id"]:
        entry = get_dua(data["fajr_dua_id"])
        if not entry:
            raise HTTPException(400, f"Unknown fajr_dua_id: {data['fajr_dua_id']}")
        data["fajr_dua_audio_file"] = entry["file"]
    if "prayer_overrides" in data and data["prayer_overrides"] is not None:
        cleaned: dict[str, dict[str, Any]] = {}
        for name, raw in data["prayer_overrides"].items():
            if name not in PRAYER_NAMES:
                raise HTTPException(400, f"Invalid prayer override: {name}")
            if raw is None:
                continue
            if not isinstance(raw, dict):
                raise HTTPException(400, f"Override for {name} must be an object")
            slot = {k: raw[k] for k in OVERRIDE_KEYS if k in raw and raw[k] is not None}
            if "dua_id" in slot:
                if not get_dua(slot["dua_id"]):
                    raise HTTPException(400, f"Unknown dua_id for {name}: {slot['dua_id']}")
            if "volume" in slot:
                slot["volume"] = int(slot["volume"])
            if "dua_volume" in slot:
                slot["dua_volume"] = int(slot["dua_volume"])
            cleaned[name] = slot
        data["prayer_overrides"] = cleaned
    if "enabled_prayers" in data and data["enabled_prayers"] is not None:
        bad = [p for p in data["enabled_prayers"] if p not in PRAYER_NAMES]
        if bad:
            raise HTTPException(400, f"Invalid prayers: {bad}")
    if data.get("boot_sound"):
        sound = data["boot_sound"]
        data["play_on_boot"] = sound != "off"
        if sound in BOOT_SOUNDS:
            data["boot_audio_file"] = BOOT_SOUNDS[sound]
    cfg = update_config(data)
    refresh_schedule(cfg)
    return public_config(cfg)


@router.get("/schedule")
def api_schedule() -> dict[str, Any]:
    cfg = load_config()
    st = get_state()
    times = st.get("today_times") or get_today_times(cfg) or {}
    return {
        "today": times,
        "schedule": st.get("schedule") or [],
        "next_prayer": st.get("next_prayer"),
        "next_prayer_at": st.get("next_prayer_at"),
        "methods": CALC_METHODS,
        "prayers": PRAYER_NAMES,
    }


@router.get("/duas")
def api_duas() -> dict[str, Any]:
    return {"duas": list_duas(), "selected": load_config().get("dua_id")}


@router.get("/audio")
def api_audio_library() -> dict[str, Any]:
    files = []
    for path in sorted(AUDIO_DIR.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".mp3", ".opus", ".ogg", ".wav", ".m4a"}:
            rel = path.relative_to(BASE_DIR).as_posix()
            files.append(
                {
                    "path": rel,
                    "name": path.name,
                    "url": f"/media/{rel}",
                    "bytes": path.stat().st_size,
                }
            )
    cfg = load_config()
    return {"files": files, "slots": slots_summary(cfg)}


def _bg(fn, *args, **kwargs) -> None:
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


@router.post("/play")
def api_play(req: PlayRequest) -> dict[str, Any]:
    cfg = load_config()
    kind = (req.kind or "test").lower()
    vol = req.volume

    if kind == "test":
        _bg(play_adhan, "Test", cfg)
        return {"ok": True, "playing": "test"}
    if kind == "boot":
        _bg(play_boot_sound, cfg)
        return {"ok": True, "playing": "boot"}
    if kind == "adhan":
        prayer = req.prayer or "Dhuhr"
        slot = profile_for(prayer, cfg)
        _bg(
            play_file,
            slot["adhan_file"],
            label=f"{prayer} adhan preview",
            volume=vol if vol is not None else slot["adhan_volume"],
            config=cfg,
        )
        return {"ok": True, "playing": "adhan", "prayer": prayer}
    if kind in {"fajr", "fajr_adhan", "fajr-adhan"}:
        slot = profile_for("Fajr", cfg)
        _bg(
            play_file,
            slot["adhan_file"],
            label="Fajr adhan preview",
            volume=vol if vol is not None else slot["adhan_volume"],
            config=cfg,
        )
        return {"ok": True, "playing": "fajr"}
    if kind == "kahf":
        _bg(
            play_file,
            cfg.get("kahf_audio_file", "audio/kahf.mp3"),
            label="Surah Kahf preview",
            volume=vol,
            config=cfg,
            timeout=120,
        )
        return {"ok": True, "playing": "kahf"}
    if kind in {"dua", "fajr_dua", "fajr-dua"}:
        is_fajr_dua = kind in {"fajr_dua", "fajr-dua"}
        slot = profile_for("Fajr" if is_fajr_dua else "Dhuhr", cfg)
        dua_id = req.dua_id or slot.get("dua_id") or cfg.get("dua_id")
        entry = get_dua(dua_id) if dua_id else None
        if not entry or not entry["available"]:
            raise HTTPException(404, f"Dua not available: {dua_id}")
        dua_vol = vol if vol is not None else slot["dua_volume"]
        _bg(
            play_file,
            entry["file"],
            label=f"Dua: {entry['title']}",
            volume=dua_vol,
            config=cfg,
        )
        return {"ok": True, "playing": entry["id"], "slot": "fajr_dua" if is_fajr_dua else "dua"}
    if kind == "file":
        if not req.path:
            raise HTTPException(400, "path required for kind=file")
        path = Path(req.path)
        if not path.is_absolute():
            path = BASE_DIR / path
        try:
            path.resolve().relative_to((BASE_DIR / "audio").resolve())
        except ValueError as e:
            raise HTTPException(400, "path must be under audio/") from e
        _bg(play_file, path, label=path.name, volume=vol, config=cfg)
        return {"ok": True, "playing": path.name}

    raise HTTPException(400, f"Unknown kind: {kind}")


@router.post("/stop")
def api_stop() -> dict[str, Any]:
    stop_playback()
    return {"ok": True}


@router.post("/skip")
def api_skip(req: SkipRequest | None = None) -> dict[str, Any]:
    prayer = req.prayer if req else None
    return {"ok": True, "state": request_skip(prayer)}


@router.post("/mute")
def api_mute(req: MuteRequest) -> dict[str, Any]:
    if req.clear:
        return {"ok": True, "state": set_mute_until(None)}
    if req.until:
        try:
            until = datetime.fromisoformat(req.until)
        except ValueError as e:
            raise HTTPException(400, f"Invalid until: {e}") from e
        return {"ok": True, "state": set_mute_until(until)}
    minutes = req.minutes or 60
    until = datetime.now().astimezone() + timedelta(minutes=minutes)
    return {"ok": True, "state": set_mute_until(until)}


@router.get("/logs")
def api_logs(lines: int = 40) -> dict[str, Any]:
    return {"lines": _tail_log(max(1, min(lines, 500)))}


@router.get("/geocode/search")
def api_geocode_search(q: str = "", limit: int = 6) -> dict[str, Any]:
    """City/address autocomplete. Proxies OSM Nominatim from the device (avoids browser CORS)."""
    query = (q or "").strip()
    if len(query) < 2:
        return {"ok": True, "offline": False, "query": query, "results": [], "error": None}
    return search_places(query, limit=limit)


@router.get("/geocode/reverse")
def api_geocode_reverse(lat: float, lon: float) -> dict[str, Any]:
    """Reverse geocode plus timezone. Timezone still works if Nominatim is offline."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(400, "lat/lon out of range")
    return reverse_place(lat, lon)


@router.get("/geocode/timezone")
def api_geocode_timezone(lat: float, lon: float) -> dict[str, Any]:
    """Offline IANA timezone from coordinates (no network)."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(400, "lat/lon out of range")
    tz = timezone_at(lat, lon)
    return {
        "ok": bool(tz),
        "latitude": lat,
        "longitude": lon,
        "timezone": tz,
        "error": None if tz else "Could not resolve timezone for that point.",
    }


@router.get("/health")
def api_health() -> dict[str, Any]:

    clock_ok, warning = check_clock_health()
    return {"ok": True, "version": __version__, "clock_ok": clock_ok, "clock_warning": warning}


@router.get("/wifi")
def api_wifi() -> dict[str, Any]:
    return wifi_status()


@router.get("/wifi/networks")
def api_wifi_networks() -> dict[str, Any]:
    try:
        nets = scan_networks(rescan=True)
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    return {"networks": nets, "wifi": wifi_status()}


@router.post("/wifi/connect")
def api_wifi_connect(req: WifiConnectRequest) -> dict[str, Any]:
    """Start joining home Wi-Fi (async). Poll GET /api/wifi until connect.phase is succeeded|failed."""
    try:
        status = connect_wifi_async(req.ssid, req.password, hidden=req.hidden)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    return {
        "ok": True,
        "wifi": status,
        "message": (
            "Connecting… this phone will lose the setup hotspot shortly. "
            "Rejoin your home Wi‑Fi, then open http://adhan.local"
        ),
    }


@router.post("/wifi/hotspot")
def api_wifi_hotspot_start() -> dict[str, Any]:
    try:
        return {"ok": True, "wifi": start_hotspot()}
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@router.delete("/wifi/hotspot")
def api_wifi_hotspot_stop() -> dict[str, Any]:
    try:
        return {"ok": True, "wifi": stop_hotspot()}
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@router.get("/wifi/setup-info")
def api_wifi_setup_info() -> dict[str, Any]:
    """Safe info for stickers / QR / first-run cards. Setup hotspot is open (no PSK)."""
    return {
        "hotspot_ssid": hotspot_ssid(),
        "hotspot_password": "",
        "hotspot_url": "http://10.42.0.1:8080/wifi",
        "lan_url": "http://adhan.local",
        "wifi": wifi_status(),
    }


class UpdateRequest(BaseModel):
    apply: bool = True
    force: bool = False


@router.get("/update")
def api_update_status() -> dict[str, Any]:
    return update_status()


@router.post("/update/check")
def api_update_check() -> dict[str, Any]:
    return check_for_updates()


@router.post("/update")
def api_update_apply(req: UpdateRequest | None = None) -> dict[str, Any]:
    body = req or UpdateRequest()
    if not body.apply:
        return check_for_updates()
    try:
        st = apply_update_async(force=body.force)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return {
        "ok": True,
        "update": st,
        "message": "Update started. The portal may restart in a few seconds.",
    }
