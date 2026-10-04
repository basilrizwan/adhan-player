"""Captive-portal detection redirects when the setup hotspot is active."""

from __future__ import annotations

from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

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
)

LOCAL_HOSTS = {
    "adhan.local",
    "adhan",
    "localhost",
    "127.0.0.1",
    "10.42.0.1",
    "0.0.0.0",
}


def _host_only(host_header: str | None) -> str:
    if not host_header:
        return ""
    return host_header.split(":")[0].strip().lower()


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

        # Lazy import so non-Pi / missing nmcli still serves the app
        try:
            from app.wifi import HOTSPOT_IP, is_hotspot_active
        except Exception:
            return await call_next(request)

        if not is_hotspot_active():
            return await call_next(request)

        host = _host_only(request.headers.get("host"))
        is_local = host in LOCAL_HOSTS or host.endswith(".local") or host.startswith("10.42.")
        is_captive_host = any(h in host for h in CAPTIVE_HOST_HINTS) if host else False
        is_captive_path = path in CAPTIVE_PATHS or path.startswith("/fwlink")

        # Android generate_204 expects 204 when online; when captive, redirect
        if path in {"/generate_204", "/gen_204"} or is_captive_host or (not is_local and is_captive_path):
            return RedirectResponse(url=f"http://{HOTSPOT_IP}:8080/wifi", status_code=302)

        # Unknown Host headers while on hotspot → send to wifi setup
        if host and not is_local:
            return RedirectResponse(url=f"http://{HOTSPOT_IP}:8080/wifi", status_code=302)

        # Root on hotspot IP should prefer wifi setup until configured
        if path == "/" and (host in {"10.42.0.1", "adhan.local", "adhan"} or not host):
            # Allow ?portal=1 to reach full UI
            if request.query_params.get("portal") != "1":
                return RedirectResponse(url="/wifi", status_code=302)

        return await call_next(request)
