"""Audio playback and prayer scheduler loop."""

from __future__ import annotations

import logging
import signal
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import BASE_DIR, PRAYER_NAMES, load_config
from app.dua import resolve_dua_path
from app.state import consume_skip, is_muted, update_state
from app.times import (
    check_clock_health,
    get_day_times,
    get_today_times,
    midnight_refresh,
)

log = logging.getLogger("adhan.player")

SLEEP_AFTER_ADHAN_SECS = 60
WAKE_BEFORE_PRAYER_SECS = 180

_shutdown = threading.Event()
_play_lock = threading.Lock()
_current_proc: subprocess.Popen | None = None
_scheduler_thread: threading.Thread | None = None


def request_shutdown() -> None:
    _shutdown.set()
    stop_playback()


def stop_playback() -> None:
    global _current_proc
    with _play_lock:
        if _current_proc and _current_proc.poll() is None:
            try:
                _current_proc.terminate()
            except Exception:
                pass
        _current_proc = None
    update_state(playing=False, playing_label=None)


def is_pi() -> bool:
    try:
        with open("/proc/device-tree/model") as f:
            return "raspberry pi" in f.read().lower()
    except FileNotFoundError:
        return False


def supports_rtcwake() -> bool:
    if not is_pi():
        return False
    try:
        result = subprocess.run(
            ["rtcwake", "--list-modes"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "mem" in result.stdout
    except Exception:
        return False


def _run_quiet(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, capture_output=True, timeout=10)
    except Exception:
        pass


def power_save_on() -> None:
    if not is_pi():
        return
    log.info("Entering power-save mode")
    _run_quiet(["sudo", "tvservice", "-o"])
    _run_quiet(
        [
            "sudo",
            "sh",
            "-c",
            "echo powersave > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor",
        ]
    )
    _run_quiet(["sudo", "sh", "-c", "echo 0 > /sys/class/leds/ACT/brightness"])


def power_save_off() -> None:
    if not is_pi():
        return
    log.info("Exiting power-save mode")
    _run_quiet(["sudo", "tvservice", "-p"])
    _run_quiet(
        [
            "sudo",
            "sh",
            "-c",
            "echo ondemand > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor",
        ]
    )
    _run_quiet(["sudo", "sh", "-c", "echo 1 > /sys/class/leds/ACT/brightness"])
    time.sleep(1)


def enter_sleep(wake_timestamp: float) -> None:
    sleep_seconds = max(0, int(wake_timestamp - time.time()))
    if sleep_seconds < 60:
        wait_until(datetime.fromtimestamp(wake_timestamp))
        return

    if supports_rtcwake():
        log.info(
            "Suspending via rtcwake for %s min (wake at %s)",
            sleep_seconds // 60,
            datetime.fromtimestamp(wake_timestamp).strftime("%H:%M"),
        )
        try:
            subprocess.run(
                ["sudo", "rtcwake", "-m", "mem", "-s", str(sleep_seconds)],
                timeout=sleep_seconds + 60,
            )
            log.info("Woke up from suspend")
            time.sleep(2)
            return
        except Exception as e:
            log.warning("rtcwake failed: %s, falling back to software sleep", e)

    log.info(
        "Software sleep for %s min (wake at %s)",
        sleep_seconds // 60,
        datetime.fromtimestamp(wake_timestamp).strftime("%H:%M"),
    )
    power_save_on()
    wait_until(datetime.fromtimestamp(wake_timestamp))
    power_save_off()


def parse_time(time_str: str, target_date: date | None = None) -> datetime:
    d = target_date or date.today()
    h, m = map(int, time_str.split(":"))
    return datetime(d.year, d.month, d.day, h, m)


def _volume_for(prayer_name: str, config: dict[str, Any]) -> int:
    if prayer_name == "Fajr":
        return int(config.get("fajr_volume", config.get("volume", 80)))
    return int(config.get("volume", 80))


def _build_play_cmd(audio_path: Path, volume: int, audio_output: str) -> list[str]:
    if sys.platform == "darwin":
        return ["afplay", "-v", str(max(0.0, min(1.0, volume / 100.0))), str(audio_path)]
    cmd = ["mpv", "--no-video", f"--volume={volume}", str(audio_path)]
    if audio_output == "hdmi":
        cmd.insert(1, "--audio-device=alsa/hdmi")
    elif audio_output == "headphone":
        cmd.insert(1, "--audio-device=alsa/default")
    return cmd


def play_file(
    audio_path: Path | str,
    *,
    label: str = "Audio",
    volume: int | None = None,
    config: dict[str, Any] | None = None,
    timeout: int = 600,
) -> bool:
    """Play an audio file on the device speaker. Returns True if finished OK."""
    global _current_proc
    cfg = config or load_config()
    path = Path(audio_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        log.error("Audio file not found: %s", path)
        update_state(last_error=f"Audio not found: {path.name}")
        return False

    vol = volume if volume is not None else int(cfg.get("volume", 80))
    audio_output = cfg.get("audio_output", "auto")
    power_save_off()
    cmd = _build_play_cmd(path, vol, audio_output)

    with _play_lock:
        if _current_proc and _current_proc.poll() is None:
            try:
                _current_proc.terminate()
            except Exception:
                pass
        update_state(playing=True, playing_label=label)
        log.info("Playing %s (%s)", label, path.name)
        try:
            _current_proc = subprocess.Popen(cmd)
            proc = _current_proc
        except FileNotFoundError:
            player = "afplay" if sys.platform == "darwin" else "mpv"
            log.error("%s not found", player)
            update_state(playing=False, playing_label=None, last_error=f"{player} not found")
            return False

    try:
        proc.wait(timeout=timeout)
        ok = proc.returncode == 0
        if ok:
            log.info("%s finished", label)
        else:
            log.warning("%s exited with code %s", label, proc.returncode)
        return ok
    except subprocess.TimeoutExpired:
        log.warning("%s playback timed out", label)
        stop_playback()
        return False
    finally:
        update_state(
            playing=False,
            playing_label=None,
            last_played=label,
            last_played_at=datetime.now(),
        )


def play_boot_sound(config: dict[str, Any] | None = None) -> None:
    """Short confirmation that the speaker came up — never the full adhan."""
    cfg = config or load_config()
    kind = (cfg.get("boot_sound") or "chime").lower()
    if kind in {"off", "none", "silent", "false"}:
        log.info("Boot sound disabled")
        return
    if kind == "adhan":
        play_adhan("Boot", cfg)
        return
    audio_file = cfg.get("boot_audio_file") or "audio/boot-chime.mp3"
    path = BASE_DIR / audio_file if not str(audio_file).startswith("/") else Path(audio_file)
    if not path.exists():
        log.warning("Boot sound missing (%s) — skipping", path)
        return
    vol = int(cfg.get("boot_volume", 45))
    play_file(path, label="Boot chime", volume=vol, config=cfg, timeout=30)


def play_adhan(prayer_name: str, config: dict[str, Any] | None = None) -> None:
    cfg = config or load_config()
    is_kahf = prayer_name == "Kahf"
    if is_kahf:
        audio_file = cfg.get("kahf_audio_file", "audio/kahf.mp3")
        timeout = (cfg.get("kahf_length_minutes", 30) + 10) * 60
        label = "Surah Kahf"
    elif prayer_name == "Fajr" and cfg.get("fajr_audio_file"):
        audio_file = cfg["fajr_audio_file"]
        timeout = 600
        label = f"Adhan for {prayer_name}"
    else:
        audio_file = cfg.get("audio_file", "audio/adhan.mp3")
        timeout = 600
        label = f"Adhan for {prayer_name}"

    volume = _volume_for(prayer_name, cfg)
    play_file(audio_file, label=label, volume=volume, config=cfg, timeout=timeout)

    # Post-adhan dua (never after Kahf or boot chime)
    if not is_kahf and cfg.get("dua_enabled", True) and prayer_name in PRAYER_NAMES + ["Test"]:
        delay = float(cfg.get("dua_delay_seconds", 2))
        if delay > 0 and not _shutdown.is_set():
            time.sleep(delay)
        dua_path = resolve_dua_path(cfg)
        if dua_path:
            play_file(
                dua_path,
                label="Dua after adhan",
                volume=volume,
                config=cfg,
                timeout=180,
            )


def wait_until(target: datetime) -> bool:
    while not _shutdown.is_set():
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0:
            return True
        time.sleep(min(30, remaining))
    return False


def append_kahf_if_scheduled(
    schedule: list[tuple[str, datetime]],
    day: date,
    times: dict[str, str] | None,
    config: dict[str, Any],
) -> None:
    if not config.get("kahf_enabled", False):
        return
    if day.weekday() != config.get("kahf_weekday", 3):
        return
    if not times or "Maghrib" not in times or "Isha" not in times:
        return

    delay = config.get("kahf_delay_minutes", 30)
    length = config.get("kahf_length_minutes", 30)
    margin = config.get("kahf_isha_margin_minutes", 5)
    kahf_dt = parse_time(times["Maghrib"], day) + timedelta(minutes=delay)
    kahf_end = kahf_dt + timedelta(minutes=length)
    isha_dt = parse_time(times["Isha"], day)

    if kahf_end + timedelta(minutes=margin) <= isha_dt:
        schedule.append(("Kahf", kahf_dt))
        log.info(
            "Surah Kahf scheduled %s at %s",
            day.strftime("%a %Y-%m-%d"),
            kahf_dt.strftime("%H:%M"),
        )
    else:
        log.warning("Skipping Surah Kahf on %s: would overlap Isha", day)


def build_full_schedule(config: dict[str, Any]) -> list[tuple[str, datetime]]:
    enabled = set(config.get("enabled_prayers", PRAYER_NAMES))
    schedule: list[tuple[str, datetime]] = []

    today = date.today()
    today_times = get_today_times(config)
    if today_times:
        for name in PRAYER_NAMES:
            if name in enabled:
                schedule.append((name, parse_time(today_times[name], today)))
        append_kahf_if_scheduled(schedule, today, today_times, config)

    tomorrow = today + timedelta(days=1)
    tomorrow_times = get_day_times(tomorrow, config)
    if tomorrow_times:
        for name in PRAYER_NAMES:
            if name in enabled:
                schedule.append((name, parse_time(tomorrow_times[name], tomorrow)))
        append_kahf_if_scheduled(schedule, tomorrow, tomorrow_times, config)

    schedule.sort(key=lambda item: item[1])
    return schedule


def find_next_prayer(schedule: list[tuple[str, datetime]]):
    now = datetime.now()
    for name, dt in schedule:
        if dt > now:
            return name, dt
    return None, None


def _publish_schedule(config: dict[str, Any]) -> list[tuple[str, datetime]]:
    schedule = build_full_schedule(config)
    today_times = get_today_times(config) or {}
    name, dt = find_next_prayer(schedule)
    clock_ok, clock_warning = check_clock_health()
    update_state(
        schedule=[{"name": n, "at": d.isoformat(timespec="seconds")} for n, d in schedule],
        today_times=today_times,
        next_prayer=name,
        next_prayer_at=dt,
        clock_ok=clock_ok,
        clock_warning=clock_warning,
    )
    return schedule


def scheduler_loop() -> None:
    log.info("Scheduler starting...")
    config = load_config()
    log.info(
        "Location: %s, %s (%s) method=%s volume=%s%% sleep=%s",
        config["latitude"],
        config["longitude"],
        config.get("location_name") or "unnamed",
        config.get("method"),
        config.get("volume"),
        config.get("sleep_enabled", False),
    )

    if config.get("play_on_boot", False):
        play_boot_sound(config)

    last_refresh_date = None

    while not _shutdown.is_set():
        config = load_config()
        sleep_enabled = config.get("sleep_enabled", False)
        today = date.today()
        if last_refresh_date != today:
            if last_refresh_date is not None:
                midnight_refresh(config)
            last_refresh_date = today

        schedule = _publish_schedule(config)
        prayer_name, prayer_dt = find_next_prayer(schedule)
        if not prayer_name:
            log.info("No upcoming prayers found, sleeping 30 minutes...")
            _shutdown.wait(1800)
            continue

        log.info("Next: %s at %s", prayer_name, prayer_dt.strftime("%H:%M (%A)"))
        wake_dt = prayer_dt - timedelta(seconds=WAKE_BEFORE_PRAYER_SECS)

        if sleep_enabled and is_pi():
            secs_until_wake = (wake_dt - datetime.now()).total_seconds()
            if secs_until_wake > SLEEP_AFTER_ADHAN_SECS:
                log.info(
                    "Sleeping in %ss, wake at %s (UI offline while asleep)",
                    SLEEP_AFTER_ADHAN_SECS,
                    wake_dt.strftime("%H:%M"),
                )
                _shutdown.wait(SLEEP_AFTER_ADHAN_SECS)
                if _shutdown.is_set():
                    break
                enter_sleep(wake_dt.timestamp())

        if not wait_until(prayer_dt):
            break
        if _shutdown.is_set():
            break

        if is_muted():
            log.info("Muted — skipping %s", prayer_name)
            continue
        if consume_skip(prayer_name):
            log.info("Skip requested — skipping %s", prayer_name)
            continue

        play_adhan(prayer_name, config)

    log.info("Scheduler stopped")


def start_scheduler() -> None:
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _shutdown.clear()
    _scheduler_thread = threading.Thread(target=scheduler_loop, name="adhan-scheduler", daemon=True)
    _scheduler_thread.start()


def install_signal_handlers() -> None:
    def _handler(signum, frame):
        log.info("Shutdown signal received")
        request_shutdown()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)
