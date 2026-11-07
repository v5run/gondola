"""The deterministic demo world for Present (all SYNTHETIC beyond the store's order history).

The demo store data has orders by channel, time and items, but no promises, courier ETAs, distances or kitchen tasks.
This module synthesizes them deterministically per order id (sha256-seeded), as fixed in
docs/architecture/TRI_WORKFLOW_API.md "Demo world for Present":

- Stations: noodles (ramen 4-5 min), fryer (Gyoza, Karaage, Takoyaki 4-6 min), assembly (Chashu Don, Chashu Bao,
  Edamame, Mochi Trio 1-3 min); drinks are packed only; then packing 1 min (2 for big orders).
- Promises: delivery = order time + app prep quote (15-25 min); pickup = order time + 15-20; dine-in = order time +
  the kitchen ticket target (the guest is present throughout).
- Courier: assigned 2-6 min after the order, 1-6 km away, arrives around the promise with noise (wider and later in
  rain); two ETA updates before arrival. Customer distance 0.5-7 km bands.
- Cooks on the line per hour from the day's labour table; rain/temperature from the calendar (optional live
  Open-Meteo with GONDOLA_WEATHER=openmeteo, offline on any error); a deterministic fryer slowdown on busy nights.

The controller never reads the `truth` fields (actual task work, actual courier/customer arrival); the replay
engine releases them only as observations (task.finished, courier.arrived, customer.arrived) when they happen.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from datetime import date as Date, timedelta
from functools import lru_cache
from pathlib import Path

from ..paths import ROOT

DB = ROOT / "data" / "gondola.duckdb"
SYNTHETIC = "synthetic: promises, couriers, distances, tasks, durations and incidents are generated per order id"

# item -> station, default minutes (one cook), hold tolerance (minutes food can wait), hands-on cook share
MENU: dict[str, dict] = {
    "Tonkotsu": {"station": "noodles", "minutes": 5.0, "hold": 4, "labour": 0.3},
    "Shoyu": {"station": "noodles", "minutes": 4.0, "hold": 4, "labour": 0.3},
    "Spicy Miso": {"station": "noodles", "minutes": 5.0, "hold": 4, "labour": 0.3},
    "Chicken Paitan": {"station": "noodles", "minutes": 4.0, "hold": 4, "labour": 0.3},
    "Veggie Miso": {"station": "noodles", "minutes": 4.0, "hold": 4, "labour": 0.3},
    "Tantanmen": {"station": "noodles", "minutes": 5.0, "hold": 4, "labour": 0.3},
    "Gyoza": {"station": "fryer", "minutes": 4.0, "hold": 3, "labour": 0.3},
    "Karaage": {"station": "fryer", "minutes": 6.0, "hold": 3, "labour": 0.3},
    "Takoyaki": {"station": "fryer", "minutes": 5.0, "hold": 3, "labour": 0.3},
    "Chashu Don": {"station": "assembly", "minutes": 3.0, "hold": 12, "labour": 1.0},
    "Chashu Bao": {"station": "assembly", "minutes": 2.0, "hold": 8, "labour": 1.0},
    "Edamame": {"station": "assembly", "minutes": 1.0, "hold": 15, "labour": 1.0},
    "Mochi Trio": {"station": "assembly", "minutes": 1.0, "hold": 30, "labour": 1.0},
    "Ramune": {"station": None, "minutes": 0.0, "hold": 60, "labour": 0.0},
    "Iced Green Tea": {"station": None, "minutes": 0.0, "hold": 60, "labour": 0.0},
    "Sapporo": {"station": None, "minutes": 0.0, "hold": 60, "labour": 0.0},
}
STATIONS = ["noodles", "fryer", "assembly", "packing"]
STATION_NAMES = {"noodles": "Noodles", "fryer": "Fryer", "assembly": "Assembly", "packing": "Packing"}
DELIVERY_APPS = ["doordash", "ubereats", "grubhub"]
CHANNELS = ["doordash", "ubereats", "grubhub", "pickup", "dine_in"]
OPEN_MIN = 11 * 60


def hm(minute: float | None) -> str | None:
    if minute is None:
        return None
    m = int(math.floor(minute + 1e-9))
    return f"{m // 60 % 24:02d}:{m % 60:02d}"


def parse_hm(s: str) -> int:
    h, m = str(s).split(":")[:2]
    return int(h) * 60 + int(m)


def u(*parts) -> float:
    """Deterministic uniform [0, 1) from any parts (sha256)."""
    d = hashlib.sha256(":".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(d[:8], "big") / 2 ** 64


def close_min(d: str) -> int:
    return (23 if Date.fromisoformat(d).weekday() in (4, 5) else 22) * 60


@lru_cache(maxsize=1)
def _con_path() -> str:
    return str(DB)


def _q(sql: str, params: list | None = None) -> list[tuple]:
    import duckdb
    con = duckdb.connect(_con_path(), read_only=True)
    try:
        return con.execute(sql, params or []).fetchall()
    finally:
        con.close()


def in_store_split(order_id: str) -> str:
    """In-store orders are split deterministically: 60% dine-in, 40% pickup (synthetic)."""
    return "dine_in" if u(order_id, "instore") < 0.6 else "pickup"


def present_channel(order_id: str, channel: str) -> str:
    return in_store_split(order_id) if channel == "in_store" else channel


# ------------------------------------------------------------------ durations
def planned_minutes(d: str) -> dict[str, float]:
    """Planning durations per item for business date d: defaults, overridden by the ledger's learned durations when
    that module exists (gondola.ledger.learning.learned_durations). Snapshotted per date so a replay is stable."""
    base = {k: v["minutes"] for k, v in MENU.items() if v["station"]}
    snap = _durations_dir() / f"durations_{d}.json"
    if snap.exists():
        try:
            data = json.loads(snap.read_text(encoding="utf-8"))
            return {**base, **{k: float(v) for k, v in data.get("minutes", {}).items() if k in base}}
        except ValueError:
            pass
    learned, source = {}, "defaults"
    try:
        from ..ledger.learning import learned_durations  # type: ignore
        prev = (Date.fromisoformat(d) - timedelta(days=1)).isoformat()   # strictly before the replayed day
        try:
            raw = learned_durations(upto_date=prev)
        except TypeError:
            raw = learned_durations()
        if isinstance(raw, dict) and "by_item" in raw:
            raw = {k: (v or {}).get("ema_min") for k, v in (raw.get("by_item") or {}).items()}
        for k, v in (raw or {}).items():
            item = k[0] if isinstance(k, tuple) else k
            if item not in base:
                continue
            val = v
            if isinstance(v, dict):
                val = v.get("minutes", v.get("avg", v.get(MENU[item]["station"])))
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue
            if 0.3 <= val <= 30:
                learned[item] = round(val, 3)
        source = "ledger.learning" if learned else "defaults"
    except Exception:  # module not built yet, or no data: defaults
        pass
    out = {**base, **learned}
    if source != "defaults":
        try:
            snap.parent.mkdir(parents=True, exist_ok=True)
            snap.write_text(json.dumps({"date": d, "source": source, "minutes": learned}), encoding="utf-8")
        except OSError:
            pass
    return out


def _durations_dir() -> Path:
    p = os.getenv("GONDOLA_PRESENT_DIR")
    return Path(p) if p else ROOT / "out" / "present"


# ------------------------------------------------------------------ data access (cached per date)
@lru_cache(maxsize=32)
def _orders(d: str) -> tuple:
    rows = _q("""SELECT o.order_id, o.created_at, o.channel, o.subtotal, list(l.item ORDER BY l.item) AS items
                 FROM orders o LEFT JOIN order_lines l USING(order_id)
                 WHERE o.business_date = ? AND o.status = 'completed'
                 GROUP BY ALL ORDER BY o.created_at, o.order_id""", [d])
    out = []
    for oid, created, ch, sub, items in rows:
        midnight = created.replace(hour=0, minute=0, second=0, microsecond=0)
        mins = (created - midnight).total_seconds() / 60 + (1440 if created.date().isoformat() != d else 0)
        out.append((oid, mins, ch, float(sub or 0), tuple(i for i in (items or []) if i)))
    return tuple(out)


@lru_cache(maxsize=32)
def _calendar(d: str) -> dict:
    rows = _q("SELECT temp_high_c, precip_mm, rain, snow, evening_rain FROM calendar WHERE date = ?", [d])
    ev = _q("SELECT event, venue, start_hour, lift FROM events WHERE date = ?", [d])
    cal = {"temp_high_c": None, "precip_mm": 0.0, "rain": False, "snow": False, "evening_rain": False}
    if rows:
        t, p, r, s, e = rows[0]
        cal = {"temp_high_c": t, "precip_mm": p or 0.0, "rain": bool(r), "snow": bool(s), "evening_rain": bool(e)}
    cal["events"] = [{"event": a, "venue": b, "start_hour": c, "lift": l} for a, b, c, l in ev]
    return cal


@lru_cache(maxsize=32)
def _cook_hours(d: str) -> float:
    rows = _q("SELECT sum(hours) FROM labour WHERE business_date = ? AND role = 'cook'", [d])
    return float(rows[0][0] or 0) if rows else 0.0


def _prior_days(d: str, n: int, same_weekday: bool) -> list[str]:
    day = Date.fromisoformat(d)
    if same_weekday:
        return [(day - timedelta(days=7 * k)).isoformat() for k in range(1, n + 1)]
    return [(day - timedelta(days=k)).isoformat() for k in range(1, n + 1)]


@lru_cache(maxsize=32)
def history_profile(d: str) -> dict:
    """Same-weekday profile from the 4 previous weeks (data strictly before d): orders per 15-min bin per channel,
    hourly share (for staffing), average work per order by resource, and basket pools by channel."""
    days = [x for x in _prior_days(d, 4, True)]
    bins: dict[tuple[int, str], float] = {}
    hours: dict[int, float] = {}
    n_days = 0
    for x in days:
        rows = _orders(x)
        if not rows:
            continue
        n_days += 1
        for oid, mins, ch, _, _ in rows:
            pc = present_channel(oid, ch)
            b = int(mins // 15) * 15
            bins[(b, pc)] = bins.get((b, pc), 0) + 1
            hours[int(mins // 60)] = hours.get(int(mins // 60), 0) + 1
    n_days = max(1, n_days)
    profile = {k: v / n_days for k, v in bins.items()}
    hourly = {h: v / n_days for h, v in hours.items()}
    # work per order and basket pools from the previous 14 days
    work = {s: 0.0 for s in STATIONS}
    work["labour"] = 0.0
    pools: dict[str, list] = {c: [] for c in CHANNELS}
    count = 0
    for x in _prior_days(d, 14, False):
        for oid, _, ch, sub, items in _orders(x):
            count += 1
            pc = present_channel(oid, ch)
            if len(pools[pc]) < 400:
                pools[pc].append(list(items))
            for it in items:
                m = MENU.get(it)
                if m and m["station"]:
                    work[m["station"]] += m["minutes"]
                    work["labour"] += m["minutes"] * m["labour"]
            work["packing"] += pack_minutes(items)
    count = max(1, count)
    return {"bins": profile, "hourly": hourly, "days": n_days,
            "work_per_order": {k: round(v / count, 3) for k, v in work.items()}, "pools": pools}


@lru_cache(maxsize=4)
def app_contribution() -> dict[str, float]:
    """Share of the subtotal the store keeps per delivery app (net payout / subtotal) from payout history."""
    rows = _q("SELECT channel, sum(net_payout) / nullif(sum(subtotal), 0) FROM payout_lines GROUP BY 1")
    out = {a: 0.75 for a in DELIVERY_APPS}
    for ch, r in rows:
        if ch in out and r is not None:
            out[ch] = round(float(r), 4)
    return out


@lru_cache(maxsize=64)
def daily_counts(d: str, n: int = 28) -> tuple:
    days = _prior_days(d, n, False)
    rows = _q("SELECT business_date, count(*) FROM orders WHERE business_date >= ? AND business_date < ? GROUP BY 1",
              [days[-1], d])
    return tuple(int(c) for _, c in rows)


def pack_minutes(items) -> float:
    return 2.0 if len(items) >= 4 else 1.0


# ------------------------------------------------------------------ weather
@lru_cache(maxsize=16)
def _openmeteo(d: str) -> dict | None:
    """Optional live weather for Pittsburgh (Open-Meteo, no key). Any error -> None (offline)."""
    try:
        import urllib.request
        url = ("https://api.open-meteo.com/v1/forecast?latitude=40.4381&longitude=-79.9220"
               "&hourly=temperature_2m,precipitation,snowfall&timezone=America%2FNew_York"
               f"&start_date={d}&end_date={d}")
        with urllib.request.urlopen(url, timeout=3) as r:
            data = json.loads(r.read().decode())
        h = data["hourly"]
        return {"temp": h["temperature_2m"], "precip": h["precipitation"], "snow": h["snowfall"]}
    except Exception:
        return None


def weather(d: str, minute: int) -> dict:
    """{rain, snow, temp_c, source}. Offline from the calendar unless GONDOLA_WEATHER=openmeteo works."""
    if os.getenv("GONDOLA_WEATHER", "").lower() == "openmeteo":
        live = _openmeteo(d)
        if live:
            h = min(23, max(0, minute // 60))
            return {"rain": (live["precip"][h] or 0) > 0.1, "snow": (live["snow"][h] or 0) > 0,
                    "temp_c": live["temp"][h], "source": "open-meteo (live)"}
    cal = _calendar(d)
    evening = minute >= 17 * 60
    rain = bool(cal["rain"] and (cal["evening_rain"] == evening or not cal["evening_rain"])) or bool(cal["evening_rain"] and evening)
    temp = cal["temp_high_c"]
    temp_c = None if temp is None else round(temp - (3.0 if evening else 0.0), 1)
    return {"rain": rain, "snow": bool(cal["snow"]), "temp_c": temp_c, "source": "calendar (offline)"}


# ------------------------------------------------------------------ the world
@dataclass
class WOrder:
    order_id: str
    channel: str              # doordash | ubereats | grubhub | pickup | dine_in
    source_channel: str       # the data's channel (in_store for pickup/dine-in)
    fulfillment: str          # delivery | pickup | dine_in
    created: float            # minutes since midnight (with seconds)
    minute: int               # the minute the order is revealed
    items: list[str]
    subtotal: float
    promise: int              # ready-by minute (app quote / pickup time / ticket target)
    customer_distance_km: float
    tasks: list[dict]         # [{task_id, item, station, nominal, truth}] truth = actual work (hidden)
    pack: dict                # {task_id, nominal, truth}
    courier: dict | None = None    # {assign_at, distance_km, arrival_off, eta_noise:[e0, e1]} (relative to promise)
    customer_arrival_off: float | None = None  # pickup: arrival relative to promise (hidden until it happens)


@dataclass
class World:
    date: str
    open_min: int
    close_min: int
    orders: list[WOrder]
    incidents: list[dict]
    cooks: dict[int, int]       # hour -> line cooks
    busy_night: bool
    calendar: dict
    profile: dict
    durations: dict[str, float]
    contribution: dict[str, float]
    notes: list[str] = field(default_factory=list)

    def cooks_at(self, minute: int) -> int:
        return self.cooks.get(minute // 60, min(self.cooks.values()) if self.cooks else 2)

    def speed(self, station: str, minute: int) -> float:
        s = 1.0
        for inc in self.incidents:
            if inc["station"] == station and inc["start"] <= minute < inc["end"]:
                s = min(s, inc["speed"])
        return s

    def by_minute(self) -> dict[int, list[WOrder]]:
        out: dict[int, list[WOrder]] = {}
        for o in self.orders:
            out.setdefault(o.minute, []).append(o)
        return out


def _line_cooks(d: str, profile: dict, kitchen) -> dict[int, int]:  # noqa: C901
    """Cook hours from the labour table spread over open hours: half flat, half following the same-weekday demand
    curve (as a manager would schedule), times the share of cooks on the line."""
    hours = list(range(OPEN_MIN // 60, close_min(d) // 60))
    total = _cook_hours(d) or 8.0 * len(hours)
    hourly = profile["hourly"]
    mean = (sum(hourly.get(h, 0) for h in hours) / len(hours)) or 1.0
    flat = total / len(hours)
    out = {}
    for h in hours:
        curve = 0.5 + 0.5 * hourly.get(h, 0) / mean
        out[h] = int(max(kitchen.min_cooks, min(kitchen.max_cooks, round(flat * curve * kitchen.line_share))))
    return out


def _incidents(d: str, busy: bool, weather_evening: bool) -> list[dict]:
    """A deterministic fryer slowdown on busy nights (same date -> same incident)."""
    if not busy:
        return []
    start = 17 * 60 + 50 + int(u(d, "incident.start") * 30)       # 17:50-18:19
    length = 20 + int(u(d, "incident.len") * 15)                   # 20-34 min
    speed = 0.6 if not weather_evening else 0.5
    return [{"kind": "fryer_slowdown", "station": "fryer", "start": start, "end": start + length, "speed": speed,
             "text": f"Fryer at {int(speed * 100)}% speed {hm(start)}-{hm(start + length)} (synthetic incident on a busy night)"}]


@lru_cache(maxsize=16)
def build(d: str, settings_digest: str = "", line_share: float = 0.5, min_cooks: int = 2, max_cooks: int = 8,
          dine_in_target: int = 12) -> World:
    """Build the deterministic world for business date d. Same inputs -> identical world."""
    from types import SimpleNamespace
    kitchen = SimpleNamespace(line_share=line_share, min_cooks=min_cooks, max_cooks=max_cooks)
    cal = _calendar(d)
    profile = history_profile(d)
    durations = planned_minutes(d)
    counts = sorted(daily_counts(d))
    expected = sum(v for v in profile["bins"].values())
    p60 = counts[int(0.6 * (len(counts) - 1))] if counts else 0
    busy = bool(cal["events"]) or bool(cal["evening_rain"]) or (bool(counts) and expected >= p60)
    rain_any = bool(cal["rain"] or cal["evening_rain"])
    orders: list[WOrder] = []
    for oid, mins, ch, sub, items in _orders(d):
        pc = present_channel(oid, ch)
        ful = "delivery" if pc in DELIVERY_APPS else pc
        minute = int(math.floor(mins))
        tasks = []
        for i, it in enumerate(items):
            m = MENU.get(it)
            if not m or not m["station"]:
                continue
            tid = f"{oid}:{i}"
            factor = 0.85 + 0.4 * u(oid, tid, "work")          # actual work 0.85-1.25 x the true default
            tasks.append({"task_id": tid, "item": it, "station": m["station"], "nominal": durations[it],
                          "truth": round(m["minutes"] * factor, 3)})
        pk = pack_minutes(items)
        pack = {"task_id": f"{oid}:pack", "nominal": pk, "truth": round(pk * (0.9 + 0.3 * u(oid, "pack")), 3)}
        rain = weather(d, minute)["rain"] if rain_any else False
        if ful == "delivery":
            promise = minute + 15 + int(u(oid, "quote") * 11)                     # app prep quote 15-25
        elif ful == "pickup":
            promise = minute + 15 + int(u(oid, "pickup") * 6)                     # 15-20
        else:
            promise = minute + dine_in_target + (3 if len(tasks) > 2 else 0)      # ticket target
        cust_km = round(0.5 + 6.5 * u(oid, "custkm") ** 1.3, 1)
        courier = None
        cust_off = None
        if ful == "delivery":
            assign = minute + 2 + int(u(oid, "assign") * 5)
            dist = round(1.0 + 5.0 * u(oid, "courierkm"), 1)
            lo, hi = (-5, 11) if rain else (-4, 6)
            arr_off = lo + (hi - lo) * u(oid, "arrive")
            spread = 5 if rain else 3
            courier = {"assign_at": assign, "distance_km": dist, "arrival_off": round(arr_off, 2),
                       "travel_min": round(dist / 0.4 + 2, 1),
                       "eta_noise": [round((u(oid, "eta0") * 2 - 1) * spread, 1), round((u(oid, "eta1") * 2 - 1), 1)]}
        elif ful == "pickup":
            cust_off = round(-4 + 12 * u(oid, "custarr"), 2)
        orders.append(WOrder(oid, pc, ch, fulfillment=ful, created=mins, minute=minute, items=list(items),
                             subtotal=sub, promise=promise, customer_distance_km=cust_km, tasks=tasks, pack=pack,
                             courier=courier, customer_arrival_off=cust_off))
    from .settings import Kitchen as _K  # noqa: F401  (kept for typing parity)
    cooks = _line_cooks(d, profile, kitchen)
    evening = weather(d, 19 * 60)
    incidents = _incidents(d, busy, bool(evening["rain"]))
    notes = [SYNTHETIC]
    if busy:
        notes.append("busy night (event, evening rain or high same-weekday volume): fryer slowdown incident modeled")
    return World(d, OPEN_MIN, close_min(d), orders, incidents, cooks, busy, cal, profile, durations,
                 app_contribution(), notes)


def world_for(d: str, settings) -> World:
    k = settings.kitchen
    return build(d, "", k.line_share, k.min_cooks, k.max_cooks, k.dine_in_target_min)


def has_data(d: str) -> bool:
    return bool(_orders(d))
