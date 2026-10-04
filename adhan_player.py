#!/usr/bin/env python3
"""Backward-compatible entrypoint.

Prefer:  python -m app.main
Or:      ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
"""

from app.main import run

if __name__ == "__main__":
    import sys

    if "--test" in sys.argv:
        from app.config import load_config
        from app.player import play_adhan
        from app.times import get_today_times

        cfg = load_config()
        times = get_today_times(cfg)
        print("Today:", times)
        play_adhan("Test", cfg)
    else:
        run()
