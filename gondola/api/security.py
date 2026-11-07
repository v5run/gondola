"""Defense in depth for a local-only demo, not authentication or a sandbox."""
from __future__ import annotations

import os
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEV_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


def _valid_host(host: str) -> bool:
    # No wildcard support: additional names must be explicitly configured.
    allowed = LOCAL_HOSTS | {h.strip().lower() for h in os.getenv("GONDOLA_ADDITIONAL_HOSTS", "").split(",") if h.strip()}
    try:
        parsed = urlsplit("//" + host)
        # Reject credentials, paths, malformed ports and IPv6 without brackets.
        return (bool(parsed.hostname) and parsed.hostname.lower() in allowed
                and parsed.username is None and parsed.password is None
                and not parsed.path and not parsed.query and not parsed.fragment
                and (parsed.port is None or 0 < parsed.port <= 65535))
    except ValueError:
        return False


def _origin_tuple(value: str):
    try:
        origin = urlsplit(value)
        if (origin.scheme not in ("http", "https") or not origin.hostname or origin.username is not None
                or origin.password is not None or origin.path or origin.query or origin.fragment):
            return None
        return (origin.scheme, origin.hostname.lower(), origin.port or (443 if origin.scheme == "https" else 80))
    except ValueError:
        return None


def allowed_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        # Non-browser local clients and signed webhooks can omit Origin. This is
        # not proof of identity and the API must not be exposed on a network.
        return True
    actual = _origin_tuple(origin)
    same = _origin_tuple(f"{request.url.scheme}://{request.headers.get('host', '')}")
    return actual is not None and (actual == same or origin in DEV_ORIGINS)


async def demo_security(request: Request, call_next):
    hosts = request.headers.getlist("host")
    if len(hosts) != 1 or not _valid_host(hosts[0]):
        return JSONResponse({"detail": "Untrusted Host"}, status_code=400)
    # Browsers provide Origin for unsafe cross-origin requests. Fetch Metadata
    # also blocks cross-site GETs (including report rebuilds); neither is auth.
    if (request.headers.get("sec-fetch-site", "").lower() == "cross-site"
            or (request.method not in ("GET", "HEAD", "OPTIONS") and not allowed_origin(request))):
        return JSONResponse({"detail": "Cross-origin request blocked"}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response
