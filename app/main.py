"""FastAPI entrypoint — serves portal UI, REST API, and starts the scheduler."""

from __future__ import annotations

import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import router as api_router
from app.captive import CaptivePortalMiddleware
from app.config import AUDIO_DIR, BASE_DIR, CACHE_DIR, WEB_DIR, load_config
from app.player import install_signal_handlers, request_shutdown, start_scheduler
from app.wifi import start_wifi_watchdog, stop_wifi_watchdog

CACHE_DIR.mkdir(exist_ok=True)
LOG_FILE = CACHE_DIR / "adhan.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3
        ),
    ],
)
log = logging.getLogger("adhan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    install_signal_handlers()
    cfg = load_config()
    log.info("Adhan Player %s starting (setup_complete=%s)", __version__, cfg.get("setup_complete"))
    start_wifi_watchdog()
    start_scheduler()
    try:
        yield
    finally:
        stop_wifi_watchdog()
        request_shutdown()
        log.info("Adhan Player stopped")


app = FastAPI(
    title="Adhan Player",
    description=(
        "Local-first Raspberry Pi adhan speaker. "
        "Configure via the web UI or this OpenAPI. "
        "Discover on the LAN as http://adhan.local:8080. "
        "If offline, joins setup hotspot Adhan-XXXX for phone Wi‑Fi onboarding."
    ),
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(CaptivePortalMiddleware)
app.include_router(api_router)

# Serve audio files for browser preview
AUDIO_DIR.mkdir(exist_ok=True)
app.mount("/media/audio", StaticFiles(directory=str(AUDIO_DIR)), name="media-audio")
# Also allow /media/<relpath under project> for dua URLs like /media/audio/dua/...
# The dua catalog uses /media/audio/dua/... which maps via the mount above.


@app.get("/media/{file_path:path}")
def media_file(file_path: str):
    """Serve files under audio/ for browser playback."""
    # Accept both audio/... and bare relative under audio
    rel = file_path
    if not rel.startswith("audio/"):
        rel = f"audio/{rel}" if not rel.startswith("/") else rel.lstrip("/")
    path = (BASE_DIR / rel).resolve()
    audio_root = AUDIO_DIR.resolve()
    try:
        path.relative_to(audio_root)
    except ValueError:
        # If path is BASE_DIR/audio/...
        try:
            path = (BASE_DIR / file_path).resolve()
            path.relative_to(audio_root)
        except ValueError as e:
            from fastapi import HTTPException

            raise HTTPException(404, "Not found") from e
    if not path.is_file():
        from fastapi import HTTPException

        raise HTTPException(404, "Not found")
    return FileResponse(path)


if WEB_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")


@app.get("/")
def index():
    index_path = WEB_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return RedirectResponse("/docs")


@app.get("/wifi")
@app.get("/wifi.html")
def wifi_setup_page():
    path = WEB_DIR / "wifi.html"
    if path.exists():
        return FileResponse(path)
    from fastapi import HTTPException

    raise HTTPException(404, "Wi‑Fi setup page missing")


@app.get("/manifest.json")
def manifest():
    path = WEB_DIR / "manifest.json"
    if path.exists():
        return FileResponse(path, media_type="application/manifest+json")
    from fastapi import HTTPException

    raise HTTPException(404)


@app.get("/sw.js")
def service_worker():
    path = WEB_DIR / "sw.js"
    if path.exists():
        return FileResponse(path, media_type="application/javascript")
    from fastapi import HTTPException

    raise HTTPException(404)


def _text_file(name: str, media: str = "text/plain; charset=utf-8"):
    path = BASE_DIR / name
    if path.exists():
        return FileResponse(path, media_type=media)
    from fastapi import HTTPException

    raise HTTPException(404)


@app.get("/llms.txt")
def llms_txt():
    return _text_file("llms.txt")


@app.get("/AGENTS.md")
def agents_md():
    return _text_file("AGENTS.md", "text/markdown; charset=utf-8")


@app.get("/docs/skill.md")
def skill_md():
    path = BASE_DIR / "docs" / "skill.md"
    if path.exists():
        return FileResponse(path, media_type="text/markdown; charset=utf-8")
    from fastapi import HTTPException

    raise HTTPException(404)


def run():
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8080,
        log_level="info",
    )


if __name__ == "__main__":
    run()
