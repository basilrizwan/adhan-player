"""Captive-portal detection when the setup hotspot is active.

Phones probe well-known URLs to decide whether a network has internet.
On the setup AP we answer those probes with the Wi-Fi setup page (HTTP 200)
instead of a 302, because several iOS/Android builds ignore or mishandle
redirects during captive detection.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from app.config import WEB_DIR

# Paths phones hit to detect captive portals
CAPTIVE_PATHS = {
    "/",
    "/hotspot-detect.html",
    "/library/test/success.html",
    "/generate_204",
    "/gen_204",
    "/connecttest.txt",
    "/ncsi.txt",
    "/fwlink/",
    "/redirect",
    "/success.txt",
    "/canonical.html",
}

CAPTIVE_HOST_HINTS = (
    "captive.apple.com",
    "www.apple.com",
    "connectivitycheck.gstatic.com",
    "clients3.google.com",
    "www.msftconnecttest.com",
    "msftconnecttest.com",
    "www.msftncsi.com",
    "detectportal.firefox.com",
    "network-test.debian.org",
    "neverssl.com",
    "captive.router",
)

LOCAL_HOSTS = {
    "adhan.local",
    "adhan",
    "localhost",
    "127.0.0.1",
    "10.42.0.1",
    "0.0.0.0",
}

# Tiny landing if wifi.html is missing. Must not contain the word Success
# (iOS treats that as "already online").
_FALLBACK_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="refresh" content="0;url=/wifi" />
  <title>Adhan Player Wi-Fi setup</title>
</head>
<body>
  <p>Continue to <a href="/wifi">Wi-Fi setup</a>.</p>
</body>
</html>
"""


def _host_only(host_header: str | None) -> str:
    if not host_header:
        return ""
    return host_header.split(":")[0].strip().lower()


def _wifi_setup_response() -> Response:
    path = WEB_DIR / "wifi.html"
    if path.exists():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return HTMLResponse(_FALLBACK_HTML, status_code=200)


class CaptivePortalMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path or "/"
        # Never intercept API, static assets, wifi page, docs, media
        if (
            path.startswith("/api/")
            or path.startswith("/assets/")
            or path.startswith("/media/")
            or path.startswith("/docs")
            or path.startswith("/openapi")
            or path.startswith("/redoc")
            or path in {"/wifi", "/wifi.html", "/llms.txt", "/AGENTS.md", "/manifest.json", "/sw.js", "/favicon.ico"}
        ):
            return await call_next(request)

        try:
            from app.wifi import hotspot_active_cached
        except Exception:
            return await call_next(request)

        if not hotspot_active_cached():
            return await call_next(request)

        host = _host_only(request.headers.get("host"))
        is_local = host in LOCAL_HOSTS or host.endswith(".local") or host.startswith("10.42.")
        is_captive_host = any(h in host for h in CAPTIVE_HOST_HINTS) if host else False
        is_captive_path = path in CAPTIVE_PATHS or path.startswith("/fwlink")

        # Detection URLs and unknown hosts: serve the setup page (HTTP 200).
        if is_captive_host or is_captive_path or (host and not is_local):
            if path == "/" and request.query_params.get("portal") == "1":
                return await call_next(request)
            return _wifi_setup_response()

        # Root on the hotspot IP / mDNS name prefers Wi-Fi setup until configured.
        if path == "/" and (host in {"10.42.0.1", "adhan.local", "adhan"} or not host):
            if request.query_params.get("portal") != "1":
                return RedirectResponse(url="/wifi", status_code=302)

        return await call_next(request)
