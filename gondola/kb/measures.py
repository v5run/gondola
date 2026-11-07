"""Measures the knowledge base recomputes from data. Used by validation (to reproduce a claimed number) and by the
Review agent's tools (so proposals quote the same numbers the validator will compute). Deterministic, no LLM.

Everything is computed as of a business date: nothing after `as_of` is read.

Scope keys (all optional): weekday ("Thu" or 0-6, Monday=0), event/condition (an event name fragment such as
"Penguins home game", or one of CONDITIONS), channel ("all", "delivery"/"apps", "in_store", "doordash", ...),
daypart ("lunch", "afternoon", "dinner") or an effect window "HH:MM-HH:MM", item ("chashu", or a menu item for
prep_min), station.
"""
from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path
from statistics import mean

import numpy as np
import pandas as pd

from ..metrics import ROOT

DB = ROOT / "data" / "gondola.duckdb"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
APPS = ["doordash", "ubereats", "grubhub"]
CONDITIONS = {"rain", "evening_rain", "snow", "dd_promo", "holiday", "cold", "school_out"}
DAYPARTS = {"lunch": ("11:00", "15:00"), "afternoon": ("15:00", "17:00"), "dinner": ("17:00", "23:59")}
EFFECT_METRICS = {"orders", "net_sales", "avg_ticket", "cancels", "unavailable_cancels"}
VALUE_METRICS = {"orders", "net_sales", "avg_ticket", "cancels", "unavailable_cancels", "sellout_rate",
                 "peak_orders_per_hour", "orders_per_cook_hour", "cash_short_rate", "prep_min", "late_orders",
                 "promises_met_pct"}
LOOKBACK_EFFECT = 120   # days searched for condition days
LOOKBACK_VALUE = 56     # recent behavior for value metrics
BASELINE_WEEKS = 8
_LOCK = threading.Lock()


# ------------------------------------------------------------------ data (one load per database version)
@lru_cache(maxsize=4)
def _load(db: str, version: int) -> dict:
    import duckdb
    con = duckdb.connect(db, read_only=True)
    try:
        bins = con.execute("""
            SELECT CAST(business_date AS DATE) AS date, channel,
                   (extract(hour FROM created_at) * 4 + extract(minute FROM created_at) // 15)::INT AS slot,
                   SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS orders,
                   SUM(CASE WHEN status='completed' THEN subtotal ELSE 0 END) AS sales,
                   SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) AS cancels,
                   SUM(CASE WHEN status='cancelled' AND cancel_reason='item_unavailable' THEN 1 ELSE 0 END) AS unavail
            FROM orders GROUP BY ALL""").df()
        cal = con.execute("SELECT CAST(date AS DATE) AS date, temp_high_c, rain, snow, evening_rain, holiday, "
                          "school_in_session, dd_promo FROM calendar").df()
        ev = con.execute("SELECT CAST(date AS DATE) AS date, string_agg(event, '; ') AS events FROM events GROUP BY 1").df()
        prep = con.execute("SELECT CAST(business_date AS DATE) AS date, par, used, sold_out FROM prep_log").df()
        lab = con.execute("SELECT CAST(business_date AS DATE) AS date, SUM(hours) AS cook_hours FROM labour "
                          "WHERE role = 'cook' GROUP BY 1").df()
        cash = con.execute("SELECT CAST(business_date AS DATE) AS date, closed_cash - expected_cash AS cash_diff "
                           "FROM cash_drawer_shifts WHERE state = 'CLOSED'").df()
    finally:
        con.close()
    for f in (bins, cal, ev, prep, lab, cash):
        f["date"] = pd.to_datetime(f["date"])
    days = bins.groupby("date")[["orders", "sales", "cancels", "unavail"]].sum().reset_index()
    days = (days.merge(cal, on="date", how="left").merge(ev, on="date", how="left").merge(prep, on="date", how="left")
            .merge(lab, on="date", how="left").merge(cash, on="date", how="left"))
    days["events"] = days["events"].fillna("")
    days["weekday"] = days.date.dt.dayofweek
    return {"bins": bins, "days": days.sort_values("date").reset_index(drop=True)}


def data(db: Path | str = DB) -> dict:
    p = Path(db)
    with _LOCK:
        return _load(str(p), p.stat().st_mtime_ns if p.exists() else 0)


# ------------------------------------------------------------------ scope helpers
def weekday_index(w) -> int | None:
    if w is None or w == "":
        return None
    if isinstance(w, (int, np.integer)):
        return int(w) % 7
    s = str(w).strip()[:3].title()
    return WEEKDAYS.index(s) if s in WEEKDAYS else None


def condition_of(scope: dict) -> str | None:
    c = scope.get("event") or scope.get("condition") or scope.get("offer")
    return str(c) if c else None


def cond_mask(days: pd.DataFrame, cond: str) -> pd.Series:
    c = cond.strip().lower()
    if c in ("rain", "snow", "evening_rain", "dd_promo"):
        return days[c].fillna(False).astype(bool)
    if c == "holiday":
        return days.holiday.notna()
    if c == "cold":
        return days.temp_high_c < 5
    if c == "school_out":
        return ~days.school_in_session.fillna(True).astype(bool)
    frag = c.replace("weekday ", "").split(" (")[0]
    return days.events.str.lower().str.contains(frag, regex=False)


def _family(cond: str) -> str:
    """'Penguins home game' -> 'penguins'; 'rain' -> 'rain' (baseline days must be free of the same family)."""
    c = cond.strip().lower()
    return c if c in CONDITIONS else c.split()[0]


def channels_of(scope: dict) -> list[str] | None:
    ch = (scope.get("channel") or "all")
    ch = str(ch).lower()
    if ch in ("all", "any", ""):
        return None
    if ch in ("delivery", "apps", "app"):
        return APPS
    if ch in ("in_store", "dine_in", "dine-in", "pickup"):
        return ["in_store"]
    return [ch]


def window_of(scope: dict, effect: dict | None = None) -> tuple[int, int] | None:
    """(first slot, last slot exclusive) in 15-minute slots, from effect.window or scope.daypart/window."""
    w = (effect or {}).get("window") or scope.get("window")
    if not w and scope.get("daypart") in DAYPARTS:
        w = "-".join(DAYPARTS[scope["daypart"]])
    if not w:
        return None
    a, b = str(w).split("-")
    s = lambda hm: int(hm[:2]) * 4 + int(hm[3:5]) // 15
    return s(a.strip()), s(b.strip()) if b.strip() != "23:59" else 96


# ------------------------------------------------------------------ per-day metric series
def series(metric: str, scope: dict, effect: dict | None = None, as_of: str | None = None, db: Path | str = DB,
           led=None) -> pd.Series:
    """One value per business day (index: Timestamp) up to `as_of`, for days the store was open."""
    d = data(db)
    days, bins = d["days"], d["bins"]
    end = pd.Timestamp(as_of) if as_of else days.date.max()
    open_days = days[(days.date <= end) & (days.orders > 0)]
    if metric in ("orders", "net_sales", "avg_ticket", "cancels", "unavailable_cancels", "peak_orders_per_hour",
                  "orders_per_cook_hour"):
        b = bins[bins.date <= end]
        chs = channels_of(scope)
        if chs:
            b = b[b.channel.isin(chs)]
        w = window_of(scope, effect)
        if w:
            b = b[(b.slot >= w[0]) & (b.slot < w[1])]
        if metric == "peak_orders_per_hour":
            h = b.assign(hour=b.slot // 4).groupby(["date", "hour"]).orders.sum().groupby("date").max()
            return h.reindex(open_days.date).fillna(0).astype(float)
        g = b.groupby("date")[["orders", "sales", "cancels", "unavail"]].sum().reindex(open_days.date).fillna(0)
        if metric == "orders":
            return g.orders.astype(float)
        if metric == "net_sales":
            return g.sales.astype(float)
        if metric == "cancels":
            return g.cancels.astype(float)
        if metric == "unavailable_cancels":
            return g.unavail.astype(float)
        if metric == "avg_ticket":
            return (g.sales / g.orders.replace(0, np.nan)).dropna()
        if metric == "orders_per_cook_hour":
            ch = open_days.set_index("date").cook_hours
            return (g.orders / ch.replace(0, np.nan)).dropna()
    if metric == "sellout_rate":
        x = open_days.dropna(subset=["sold_out"]).set_index("date").sold_out
        return x.astype(float)
    if metric == "cash_short_rate":
        x = open_days.dropna(subset=["cash_diff"]).set_index("date").cash_diff
        return (x < -5).astype(float)
    if metric in ("prep_min", "late_orders", "promises_met_pct"):
        return _ledger_series(metric, scope, end, led)
    raise KeyError(f"unknown metric '{metric}'")


def _ledger_series(metric: str, scope: dict, end: pd.Timestamp, led=None) -> pd.Series:
    """Metrics that only exist in the ledger (task timings and promises written by Present)."""
    from ..ledger import ledger as _ledger
    led = led or _ledger()
    vals: dict = {}
    if metric == "prep_min":
        for e in led.query(None, ["task.finished"]):
            p = e.payload
            if e.date > str(end.date()) or p.get("actual_min") is None:
                continue
            if scope.get("item") and str(p.get("item", "")).lower() != str(scope["item"]).lower():
                continue
            if scope.get("station") and p.get("station") != scope["station"]:
                continue
            vals.setdefault(e.date, []).append(float(p["actual_min"]))
    else:
        for e in led.query(None, ["order.handed_off"]):
            p = e.payload
            if e.date > str(end.date()) or p.get("late_min") is None:
                continue
            vals.setdefault(e.date, []).append(float(p["late_min"]))
    out = {}
    for k, v in vals.items():
        if metric == "prep_min":
            out[pd.Timestamp(k)] = mean(v)
        elif metric == "late_orders":
            out[pd.Timestamp(k)] = float(sum(1 for x in v if x > 0))
        else:
            out[pd.Timestamp(k)] = sum(1 for x in v if x <= 0) / len(v)
    return pd.Series(out, dtype=float).sort_index()


# ------------------------------------------------------------------ the two measurements
def matching_days(scope: dict, as_of: str, lookback: int, db: Path | str = DB, with_condition: bool = True) -> pd.DatetimeIndex:
    days = data(db)["days"]
    end = pd.Timestamp(as_of)
    x = days[(days.date <= end) & (days.date > end - pd.Timedelta(days=lookback)) & (days.orders > 0)]
    wd = weekday_index(scope.get("weekday"))
    if wd is not None:
        x = x[x.weekday == wd]
    cond = condition_of(scope)
    if cond and with_condition:
        x = x[cond_mask(x, cond)]
    return pd.DatetimeIndex(x.date)


def effect(metric: str, scope: dict, eff: dict | None = None, as_of: str | None = None, db: Path | str = DB,
           lookback: int = LOOKBACK_EFFECT, led=None) -> dict:
    """Same weekday with vs without the condition: for each condition day in the lookback, the metric against the mean
    of the same weekday over the previous BASELINE_WEEKS weeks without that condition (and no holiday).
    Returns {change_pct, n, evidence, per_day:[{date, value, baseline, change_pct}], agreement}."""
    cond = condition_of(scope)
    if not cond:
        return {"change_pct": None, "n": 0, "evidence": [], "per_day": [], "agreement": None,
                "error": "event_effect needs scope.event (or condition)"}
    if metric not in EFFECT_METRICS:
        return {"change_pct": None, "n": 0, "evidence": [], "per_day": [], "agreement": None,
                "error": f"metric '{metric}' is not an effect metric ({sorted(EFFECT_METRICS)})"}
    days = data(db)["days"]
    as_of = as_of or str(days.date.max().date())
    s = series(metric, scope, eff, as_of, db, led)
    fam = _family(cond)
    dirty = cond_mask(days, fam) | cond_mask(days, cond) | days.holiday.notna()
    dirty = pd.Series(dirty.values, index=days.date)
    per_day = []
    for d in matching_days(scope, as_of, lookback, db):
        if d not in s.index:
            continue
        lo = d - pd.Timedelta(weeks=BASELINE_WEEKS)
        base_days = [b for b in pd.date_range(lo, d - pd.Timedelta(days=1)) if b.dayofweek == d.dayofweek
                     and b in s.index and not bool(dirty.get(b, True))]
        if len(base_days) < 2:
            continue
        base = float(s.loc[base_days].mean())
        if base <= 0:
            continue
        v = float(s.loc[d])
        per_day.append({"date": str(d.date()), "value": round(v, 2), "baseline": round(base, 2),
                        "change_pct": round((v / base - 1) * 100, 1)})
    if not per_day:
        return {"change_pct": None, "n": 0, "evidence": [], "per_day": [], "agreement": None}
    ch = mean(p["change_pct"] for p in per_day)
    agree = sum(1 for p in per_day if np.sign(p["change_pct"]) == np.sign(ch)) / len(per_day)
    return {"change_pct": round(ch, 1), "n": len(per_day), "evidence": [p["date"] for p in per_day],
            "per_day": per_day[-12:], "agreement": round(agree, 2)}


def value(metric: str, scope: dict, eff: dict | None = None, as_of: str | None = None, db: Path | str = DB,
          lookback: int = LOOKBACK_VALUE, led=None, start: str | None = None) -> dict:
    """Mean of the metric over the matching days (weekday / condition) in the lookback, or from `start` to `as_of`.
    Returns {value, n, evidence}."""
    if metric not in VALUE_METRICS:
        return {"value": None, "n": 0, "evidence": [], "error": f"unknown metric '{metric}' ({sorted(VALUE_METRICS)})"}
    days = data(db)["days"]
    as_of = as_of or str(days.date.max().date())
    s = series(metric, scope, eff, as_of, db, led)
    if start is not None:
        lookback = (pd.Timestamp(as_of) - pd.Timestamp(start)).days + 1
    if metric in ("prep_min", "late_orders", "promises_met_pct"):
        idx = s.index[(s.index <= pd.Timestamp(as_of)) & (s.index > pd.Timestamp(as_of) - pd.Timedelta(days=lookback))]
        wd = weekday_index(scope.get("weekday"))
        if wd is not None:
            idx = idx[idx.dayofweek == wd]
    else:
        idx = matching_days(scope, as_of, lookback, db).intersection(s.index)
    if not len(idx):
        return {"value": None, "n": 0, "evidence": []}
    v = float(s.loc[idx].mean())
    return {"value": round(v, 4 if metric.endswith("rate") or metric.endswith("pct") else 2), "n": int(len(idx)),
            "evidence": [str(d.date()) for d in idx][-12:]}


def day_conditions(date: str, db: Path | str = DB) -> dict:
    """What was special about a day: {weekday, events:[...], rain, evening_rain, snow, dd_promo, holiday, cold}."""
    days = data(db)["days"]
    r = days[days.date == pd.Timestamp(date)]
    wd = WEEKDAYS[pd.Timestamp(date).dayofweek]
    if r.empty:
        return {"weekday": wd, "events": [], "open": False}
    r = r.iloc[0]
    ev = [e.strip() for e in str(r.events or "").split(";") if e.strip()]
    return {"weekday": wd, "events": ev, "rain": bool(r.rain), "evening_rain": bool(r.evening_rain), "snow": bool(r.snow),
            "dd_promo": bool(r.dd_promo), "holiday": r.holiday if isinstance(r.holiday, str) else None,
            "cold": bool(r.temp_high_c < 5) if r.temp_high_c == r.temp_high_c else False,
            "temp_high_c": float(r.temp_high_c) if r.temp_high_c == r.temp_high_c else None,
            "open": bool(r.orders > 0), "sold_out": bool(r.sold_out) if r.sold_out == r.sold_out else None,
            "par": float(r.par) if r.par == r.par else None, "used": float(r.used) if r.used == r.used else None}


def event_family_name(event: str) -> str:
    """'Steelers home game (TNF)' -> 'Steelers home game'."""
    return event.split(" (")[0].strip()
