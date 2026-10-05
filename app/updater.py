"""Git-based auto-update against the public GitHub repo."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.config import BASE_DIR, load_config

log = logging.getLogger("adhan.update")

DEFAULT_REPO = "https://github.com/basilrizwan/adhan-player.git"
DEFAULT_BRANCH = "main"

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()
_state: dict[str, Any] = {
    "busy": False,
    "last_check_at": None,
    "last_apply_at": None,
    "last_result": None,
    "last_error": None,
    "local_commit": None,
    "remote_commit": None,
    "update_available": False,
    "next_midnight": None,
}


def _script() -> Path:
    return BASE_DIR / "scripts" / "update.sh"


def _git(*args: str, timeout: int = 45) -> str:
    r = subprocess.run(
        ["git", *args],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "git failed").strip())
    return (r.stdout or "").strip()


def _is_git_repo() -> bool:
    return (BASE_DIR / ".git").is_dir()


def git_status_snapshot() -> dict[str, Any]:
    cfg = load_config()
    repo = cfg.get("update_repo") or DEFAULT_REPO
    branch = cfg.get("update_branch") or DEFAULT_BRANCH
    out: dict[str, Any] = {
        "repo": repo,
        "branch": branch,
        "is_git": _is_git_repo(),
        "local_commit": None,
        "remote_commit": None,
        "update_available": False,
        "auto_update": cfg.get("auto_update", True),
        "update_on_boot": cfg.get("update_on_boot", True),
        "update_at_midnight": cfg.get("update_at_midnight", True),
    }
    if not _is_git_repo():
        out["note"] = "Not a git checkout yet — first apply will clone from GitHub."
        return out
    try:
        out["local_commit"] = _git("rev-parse", "HEAD")
    except Exception as e:
        out["last_error"] = str(e)
    return out


def check_for_updates() -> dict[str, Any]:
    """Fetch origin and compare commits. Does not apply."""
    cfg = load_config()
    repo = cfg.get("update_repo") or DEFAULT_REPO
    branch = cfg.get("update_branch") or DEFAULT_BRANCH
    env = os.environ.copy()
    env["ADHAN_UPDATE_URL"] = repo
    env["ADHAN_UPDATE_BRANCH"] = branch

    with _lock:
        _state["busy"] = True
        _state["last_check_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        if not _script().exists():
            raise RuntimeError("scripts/update.sh is missing")
        r = subprocess.run(
            ["bash", str(_script()), "--check"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=90,
            env=env,
            check=False,
        )
        text = (r.stdout or "") + (r.stderr or "")
        available = r.returncode == 2
        local = remote = None
        for line in text.splitlines():
            if "local " in line:
                local = line.split()[-1]
            if "remote " in line:
                remote = line.split()[-1]
            if line.startswith("UP_TO_DATE"):
                local = remote = line.split()[-1]
            if line.startswith("UPDATE_AVAILABLE"):
                parts = line.split()
                if len(parts) >= 4:
                    local, remote = parts[1], parts[3]
        with _lock:
            _state.update(
                {
                    "busy": False,
                    "last_result": "available" if available else "up_to_date",
                    "last_error": None if r.returncode in (0, 2) else text.strip(),
                    "local_commit": local,
                    "remote_commit": remote,
                    "update_available": available,
                }
            )
        return status()
    except Exception as e:
        log.warning("Update check failed: %s", e)
        with _lock:
            _state.update({"busy": False, "last_error": str(e), "last_result": "error"})
        return status()


def apply_update(*, force: bool = False, unattended: bool = False) -> dict[str, Any]:
    cfg = load_config()
    repo = cfg.get("update_repo") or DEFAULT_REPO
    branch = cfg.get("update_branch") or DEFAULT_BRANCH
    env = os.environ.copy()
    env["ADHAN_UPDATE_URL"] = repo
    env["ADHAN_UPDATE_BRANCH"] = branch
    if unattended:
        env["ADHAN_UNATTENDED"] = "1"

    with _lock:
        if _state.get("busy"):
            raise RuntimeError("An update is already running")
        _state["busy"] = True
        _state["last_apply_at"] = datetime.now().isoformat(timespec="seconds")

    args = ["bash", str(_script())]
    if force:
        args.append("--force")

    try:
        log.info("Applying update from %s (%s)", repo, branch)
        r = subprocess.run(
            args,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
            check=False,
        )
        text = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        ok = r.returncode == 0
        with _lock:
            _state.update(
                {
                    "busy": False,
                    "last_result": "updated" if ok and "UPDATED" in text else ("up_to_date" if ok else "error"),
                    "last_error": None if ok else text,
                    "update_available": False if ok else _state.get("update_available"),
                    "log_tail": text[-2000:],
                }
            )
        if not ok:
            log.error("Update failed: %s", text[-500:])
        else:
            log.info("Update finished: %s", text.splitlines()[-1] if text else "ok")
        return status()
    except Exception as e:
        log.error("Update apply failed: %s", e)
        with _lock:
            _state.update({"busy": False, "last_error": str(e), "last_result": "error"})
        return status()


def apply_update_async(*, force: bool = False) -> dict[str, Any]:
    def _job():
        try:
            apply_update(force=force)
        except Exception as e:
            log.error("Async update error: %s", e)

    threading.Thread(target=_job, name="adhan-update", daemon=True).start()
    return status()


def should_skip_for_prayer() -> bool:
    try:
        from app.state import get_state

        st = get_state()
        if st.get("playing"):
            return True
        nxt = st.get("next_prayer_at")
        if not nxt:
            return False
        when = datetime.fromisoformat(nxt) if isinstance(nxt, str) else nxt
        return 0 <= (when - datetime.now()).total_seconds() < 10 * 60
    except Exception:
        return False


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(load_config().get("timezone") or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _next_midnight() -> datetime:
    now = datetime.now(_tz())
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=8, second=0, microsecond=0)
    if now.hour == 0 and now.minute < 8:
        nxt = now.replace(hour=0, minute=8, second=0, microsecond=0)
    return nxt


def status() -> dict[str, Any]:
    snap = git_status_snapshot()
    with _lock:
        merged = {**snap, **{k: v for k, v in _state.items() if v is not None}}
    merged["next_midnight"] = _next_midnight().isoformat(timespec="seconds")
    return merged


def _maybe_apply(reason: str) -> None:
    cfg = load_config()
    if not cfg.get("auto_update", True):
        log.info("Auto-update disabled; skip (%s)", reason)
        return
    if should_skip_for_prayer():
        log.info("Skipping update (%s): playback or prayer soon", reason)
        return
    try:
        from app.wifi import has_internet, is_hotspot_active

        if is_hotspot_active() or not has_internet():
            log.info("Skipping update (%s): no internet", reason)
            return
    except Exception:
        pass
    st = check_for_updates()
    if st.get("update_available"):
        log.info("Update available (%s) — applying", reason)
        apply_update(unattended=True)
    else:
        log.info("No update (%s)", reason)


def updater_loop() -> None:
    cfg = load_config()
    if cfg.get("update_on_boot", True):
        # Let Wi‑Fi / NTP settle
        _stop.wait(90)
        if not _stop.is_set():
            try:
                _maybe_apply("boot")
            except Exception as e:
                log.warning("Boot update failed: %s", e)

    while not _stop.is_set():
        cfg = load_config()
        if not cfg.get("update_at_midnight", True):
            _stop.wait(3600)
            continue
        target = _next_midnight()
        with _lock:
            _state["next_midnight"] = target.isoformat(timespec="seconds")
        now = datetime.now(_tz())
        wait = max(30.0, (target - now).total_seconds())
        log.info("Next auto-update at %s (in %d min)", target.strftime("%Y-%m-%d %H:%M"), int(wait // 60))
        if _stop.wait(wait):
            break
        try:
            _maybe_apply("midnight")
        except Exception as e:
            log.warning("Midnight update failed: %s", e)
        # Avoid double-fire in the same minute
        _stop.wait(90)


def start_updater() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=updater_loop, name="adhan-updater", daemon=True)
    _thread.start()


def stop_updater() -> None:
    _stop.set()
