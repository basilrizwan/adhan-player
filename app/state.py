"""Runtime player state shared by the scheduler and HTTP API."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

_lock = threading.RLock()

_state: dict[str, Any] = {
    "playing": False,
    "playing_label": None,
    "next_prayer": None,
    "next_prayer_at": None,
    "last_played": None,
    "last_played_at": None,
    "mute_until": None,
    "skip_next": False,
    "skip_prayer": None,
    "schedule": [],
    "today_times": {},
    "clock_ok": True,
    "clock_warning": None,
    "started_at": datetime.now().isoformat(timespec="seconds"),
    "last_error": None,
}


def get_state() -> dict[str, Any]:
    with _lock:
        out = dict(_state)
        mu = _state.get("mute_until")
        out["muted"] = bool(mu and datetime.now() < mu)
        out["mute_until"] = mu.isoformat(timespec="seconds") if isinstance(mu, datetime) else mu
        npa = _state.get("next_prayer_at")
        out["next_prayer_at"] = (
            npa.isoformat(timespec="seconds") if isinstance(npa, datetime) else npa
        )
        lpa = _state.get("last_played_at")
        out["last_played_at"] = (
            lpa.isoformat(timespec="seconds") if isinstance(lpa, datetime) else lpa
        )
        return out


def update_state(**kwargs) -> dict[str, Any]:
    with _lock:
        _state.update(kwargs)
        return get_state()


def is_muted() -> bool:
    with _lock:
        mu = _state.get("mute_until")
        return bool(mu and datetime.now() < mu)


def consume_skip(prayer_name: str) -> bool:
    """Return True if this prayer should be skipped, and clear the flag."""
    with _lock:
        if not _state.get("skip_next"):
            return False
        target = _state.get("skip_prayer")
        if target and target != prayer_name:
            return False
        _state["skip_next"] = False
        _state["skip_prayer"] = None
        return True


def set_mute_until(until: datetime | None) -> dict[str, Any]:
    return update_state(mute_until=until)


def request_skip(prayer_name: str | None = None) -> dict[str, Any]:
    return update_state(skip_next=True, skip_prayer=prayer_name)
