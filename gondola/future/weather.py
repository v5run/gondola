"""Optional live weather: Open-Meteo daily forecast for Squirrel Hill, Pittsburgh (no key needed).

Off unless GONDOLA_WEATHER=openmeteo. Never runs under pytest. Any error (network, timeout, bad JSON) returns {} and
the forecast falls back to the offline calendar / seasonal normals. Results are cached for 30 minutes.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

LAT, LON = 40.4381, -79.9222
URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
       "&daily=temperature_2m_max,precipitation_sum,snowfall_sum,precipitation_hours"
       "&timezone=America%2FNew_York&forecast_days=8")
_CACHE: dict = {}
TTL = 1800
MAX_RESPONSE_BYTES = 256 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not allow the fixed provider URL to redirect to an arbitrary host.
        return None


def enabled() -> bool:
    return os.getenv("GONDOLA_WEATHER", "").strip().lower() == "openmeteo" and "PYTEST_CURRENT_TEST" not in os.environ


def _fetch(timeout: float = 4.0) -> dict:
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(URL.format(lat=LAT, lon=LON), timeout=timeout) as r:  # fixed HTTPS URL
        body = r.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("Weather response too large")
        return json.loads(body.decode("utf-8"))


def parse(js: dict) -> dict[str, dict]:
    """Open-Meteo daily JSON -> {date: {temp_high_c, precip_mm, rain, snow, source}}."""
    d = js["daily"]
    out = {}
    for i, day in enumerate(d["time"]):
        p = float(d["precipitation_sum"][i] or 0.0)
        sn = float(d["snowfall_sum"][i] or 0.0)
        t = d["temperature_2m_max"][i]
        out[day] = {"temp_high_c": float(t) if t is not None else None, "precip_mm": p,
                    "snow": sn >= 0.5, "rain": p >= 1.0 and sn < 0.5, "source": "open-meteo"}
    return out


def daily_forecast(fetch=None) -> dict[str, dict]:
    """{date: weather} from the live feed, or {} when disabled or failing. `fetch` is injectable for tests."""
    if fetch is None and not enabled():
        return {}
    now = time.time()
    if fetch is None and _CACHE.get("t", 0) > now - TTL:
        return _CACHE["v"]
    try:
        v = parse((fetch or _fetch)())
    except Exception:  # noqa: BLE001 - degrade to offline on any error
        v = {}
    if fetch is None:
        _CACHE.update(t=now, v=v)
    return v
