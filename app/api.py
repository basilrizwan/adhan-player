"""REST API for the local Adhan Player portal and agents."""

from __future__ import annotations

import socket
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import __version__
from app.config import (
    AUDIO_DIR,
    BASE_DIR,
    CALC_METHODS,
    PRAYER_NAMES,
    load_config,
    public_config,
    update_config,
)
from app.dua import get_dua, list_duas
from app.player import play_adhan, play_file, stop_playback
from app.state import get_state, request_skip, set_mute_until, update_state
from app.times import check_clock_health, get_today_times

router = APIRouter(prefix="/api")


class ConfigPatch(BaseModel):
    setup_complete: Optional[bool] = None
    device_name: Optional[str] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    method: Optional[int] = None
    school: Optional[int] = None
    volume: Optional[int] = Field(default=None, ge=0, le=100)
    fajr_volume: Optional[int] = Field(default=None, ge=0, le=100)
    audio_file: Optional[str] = None
    fajr_audio_file: Optional[str] = None
    enabled_prayers: Optional[list[str]] = None
    audio_output: Optional[str] = None
    sleep_enabled: Optional[bool] = None
    play_on_boot: Optional[bool] = None
    dua_enabled: Optional[bool] = None
    dua_id: Optional[str] = None
    dua_audio_file: Optional[str] = None
    dua_delay_seconds: Optional[float] = None
    dua_include_promise: Optional[bool] = None
    kahf_enabled: Optional[bool] = None
    kahf_audio_file: Optional[str] = None
    kahf_delay_minutes: Optional[int] = None
    kahf_weekday: Optional[int] = None
    kahf_length_minutes: Optional[int] = None
    kahf_isha_margin_minutes: Optional[int] = None
    use_offline_times: Optional[bool] = None
    aladhan_refresh: Optional[bool] = None


class PlayRequest(BaseModel):
    kind: str = Field(
        description="adhan | fajr | dua | kahf | file | test",
        default="test",
    )
    dua_id: Optional[str] = None
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
        "urls": [f"http://adhan.local:8080"] + [f"http://{ip}:8080" for ip in _local_ips()],
        "clock_ok": clock_ok,
        "clock_warning": clock_warning,
        "state": st,
        "volume": cfg.get("volume"),
        "sleep_enabled": cfg.get("sleep_enabled", False),
        "dua_enabled": cfg.get("dua_enabled", True),
        "dua_id": cfg.get("dua_id"),
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
    if "enabled_prayers" in data and data["enabled_prayers"] is not None:
        bad = [p for p in data["enabled_prayers"] if p not in PRAYER_NAMES]
        if bad:
            raise HTTPException(400, f"Invalid prayers: {bad}")
    if "method" in data and data["method"] is not None and data["method"] not in CALC_METHODS:
        # Allow unknown methods that Aladhan might support, but warn via response
        pass
    cfg = update_config(data)
    # Refresh schedule snapshot
    times = get_today_times(cfg)
    update_state(today_times=times or {})
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
    return {"files": files}


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
    if kind == "adhan":
        _bg(
            play_file,
            cfg.get("audio_file", "audio/adhan.mp3"),
            label="Adhan preview",
            volume=vol,
            config=cfg,
        )
        return {"ok": True, "playing": "adhan"}
    if kind == "fajr":
        _bg(
            play_file,
            cfg.get("fajr_audio_file", "audio/fajr.mp3"),
            label="Fajr adhan preview",
            volume=vol if vol is not None else cfg.get("fajr_volume"),
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
    if kind == "dua":
        dua_id = req.dua_id or cfg.get("dua_id")
        entry = get_dua(dua_id) if dua_id else None
        if not entry or not entry["available"]:
            raise HTTPException(404, f"Dua not available: {dua_id}")
        _bg(
            play_file,
            entry["file"],
            label=f"Dua: {entry['title']}",
            volume=vol,
            config=cfg,
        )
        return {"ok": True, "playing": entry["id"]}
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
    until = datetime.now() + timedelta(minutes=minutes)
    return {"ok": True, "state": set_mute_until(until)}


@router.get("/logs")
def api_logs(lines: int = 40) -> dict[str, Any]:
    return {"lines": _tail_log(max(1, min(lines, 500)))}


@router.get("/health")
def api_health() -> dict[str, Any]:
    clock_ok, warning = check_clock_health()
    return {"ok": True, "version": __version__, "clock_ok": clock_ok, "clock_warning": warning}
