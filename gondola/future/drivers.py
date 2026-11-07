"""Drivers: "Expected tonight" and why, each effect measured from the store's own history.

Measurement (`measure`): over the 365 days before the date, open days that are not holidays, on the SAME WEEKDAY:
    effect = mean(orders on days WITH the driver) / mean(orders on days WITHOUT it) - 1
Fewer than 3 same-weekday examples -> estimate=True and the comparison falls back to every weekday, each day
taken relative to its own weekday's normal (mean of that weekday's days without the driver). No examples at all
-> the events table's planned lift if there is one (estimate=True), else no effect and a "no past examples" flag.

These are plain with/without comparisons (not causal): season and other drivers can ride along. The LightGBM day
model already uses most of these features; drivers explain the forecast, they are not added on top of it (the
Outlook agent decides whether a bounded adjustment is warranted).

effect_pct is in percent (+8.3 means +8.3% orders).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import base as B
from .base import CHANNEL_NAME, CHANNELS, DB

MIN_EXAMPLES = 3
LOOKBACK_DAYS = 365
GAME_TEAMS = {"Penguins": "puck drop", "Steelers": "kickoff", "Pirates": "first pitch", "Super Bowl": "kickoff"}
DOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
COLD_C, HOT_C = 2.0, 28.0


def measure(hist: pd.DataFrame, mask: pd.Series, dow: int, without: pd.Series | None = None) -> dict:
    """hist: daily rows (business_date, dow, orders); mask: bool Series (driver on). without: which days count as
    the comparison group (default: ~mask). Returns {effect (fraction or None), n, n_without, estimate, scope,
    evidence (dates with the driver, newest first)}."""
    mask = mask.reindex(hist.index).fillna(False).astype(bool)
    without = (~mask if without is None else without.reindex(hist.index).fillna(False).astype(bool)) & ~mask
    same = hist.dow == dow
    w, wo = hist[same & mask], hist[same & without]
    ev = [B.ddate(x) for x in hist[mask].business_date.sort_values(ascending=False)]
    if len(w) >= MIN_EXAMPLES and len(wo) >= MIN_EXAMPLES:
        return {"effect": float(w.orders.mean() / wo.orders.mean() - 1), "n": int(len(w)), "n_without": int(len(wo)),
                "estimate": False, "scope": "same_weekday", "evidence": [B.ddate(x) for x in w.business_date.sort_values(ascending=False)]}
    normal = hist[without].groupby("dow").orders.mean()
    allw = hist[mask & hist.dow.isin(normal.index)]
    if len(allw) == 0 or normal.empty:
        return {"effect": None, "n": int(mask.sum()), "n_without": int(len(wo)), "estimate": True, "scope": "none", "evidence": ev}
    rel = allw.orders / allw.dow.map(normal)
    return {"effect": float(rel.mean() - 1), "n": int(len(allw)), "n_without": int(without.sum()), "estimate": True,
            "scope": "all_weekdays", "evidence": ev}


def history(date: str, db=DB, upto: str | None = None) -> pd.DataFrame:
    """Open, non-holiday days in the LOOKBACK before `date` (nothing of `date` or later, nor of `upto` or later)."""
    d = pd.Timestamp(date)
    df = B.daily(db, upto=min(B.ddate(date), upto or B.ddate(date)))
    h = df[(df.business_date >= d - pd.Timedelta(days=LOOKBACK_DAYS)) & (df.orders > 0)].copy()
    h = h[h.holiday_factor.fillna(1.0) == 1.0].reset_index(drop=True)
    h["dow"] = h.business_date.dt.dayofweek
    for c in ("rain", "snow", "school_in_session", "dd_promo", "evening_rain"):
        h[c] = h[c].fillna(False).astype(bool)
    return h


def _events(db=DB) -> pd.DataFrame:
    def load():
        from ..metrics import Store
        e = Store(db).df("SELECT date, event, venue, start_hour, lift FROM events")
        e["date"] = pd.to_datetime(e.date)
        return e
    return B.CACHE.get(("events", str(db), B.db_version(db)), load)


def team_of(event: str) -> str:
    return next((t for t in GAME_TEAMS if str(event).startswith(t)), str(event))


def _clock(h: float) -> str:
    return B.hm(int(round(h * 60)))


def _window_effect(date_with: list[str], date_without: list[str], h0: float, h1: float, db=DB) -> tuple[float | None, str | None]:
    """Orders in [h0, h1) on with- vs without-days, and which channel carries the difference."""
    if not date_with or not date_without:
        return None, None
    cnt = B.counts(db)
    b0, b1 = int(h0 * 4), int(np.ceil(h1 * 4))
    x = cnt[(cnt.bin >= b0) & (cnt.bin < b1)]

    def per_day(ds):
        y = x[x.business_date.isin(pd.to_datetime(ds))]
        return y.groupby("channel").n.sum().reindex(CHANNELS, fill_value=0) / len(ds)
    a, b = per_day(date_with), per_day(date_without)
    lift = float(a.sum() / b.sum() - 1) if b.sum() > 0 else None
    diff = a - b
    up = diff.clip(lower=0)
    note = None
    if diff.sum() > 0 and up.sum() > 0:
        top = up.idxmax()
        if up[top] / up.sum() > 0.5:
            note = f"mostly {CHANNEL_NAME[top]}"
        elif up[["doordash", "ubereats", "grubhub"]].sum() / up.sum() > 0.7:
            note = "mostly delivery"
        if diff["in_store"] < 0 and note:
            note += ", in-store down"
    elif diff.sum() < 0:
        down = (-diff).clip(lower=0)
        if down.sum() > 0:
            top = down.idxmax()
            note = f"fewer {CHANNEL_NAME[top]} orders" if down[top] / down.sum() > 0.5 else None
    return lift, note


def _pct(x: float | None) -> float:
    return round(100 * x, 1) if x is not None else 0.0


def _driver(kind, label, m: dict, why: str, time=None, window=None, channel_note=None, extra=None) -> dict:
    return {"kind": kind, "label": label, "time": time, "window": window, "effect_pct": _pct(m.get("effect")),
            "channel_note": channel_note, "why": why, "estimate": bool(m.get("estimate", True)),
            "examples": int(m.get("n") or 0), "compared_with": int(m.get("n_without") or 0),
            "evidence": list(m.get("evidence") or [])[:6], **(extra or {})}


def calendar_row(date: str, db=DB) -> dict | None:
    from ..metrics import Store
    c = Store(db).df("SELECT * FROM calendar WHERE date = ?", [B.ddate(date)])
    return None if c.empty else {k: (None if (isinstance(v, float) and v != v) else v) for k, v in c.iloc[0].to_dict().items()}


def drivers(date: str, db=DB, cal_row: dict | None = None, weather_known: bool = True, events: pd.DataFrame | None = None,
            weather_note: str | None = None, now=None) -> list[dict]:
    """Drivers for `date`, ordered by |effect_pct|. cal_row/events default to the calendar and events tables (the
    horizon passes synthesized rows for days past the calendar). History stops before `date` and before any day
    that is not complete at `now` (store clock if None)."""
    date = B.ddate(date)
    d = pd.Timestamp(date)
    dow, dn = int(d.dayofweek), DOW[int(d.dayofweek)]
    hist = history(date, db, upto=B.history_upto(date, now, db))
    if hist.empty:
        return []
    cal = cal_row if cal_row is not None else (calendar_row(date, db) or {})
    allev = _events(db)
    ev_today = events if events is not None else allev[allev.date == d]
    past_ev = allev[(allev.date < d) & (allev.date >= d - pd.Timedelta(days=LOOKBACK_DAYS))]
    event_days = hist.business_date.isin(set(past_ev.date))
    out: list[dict] = []

    # ---- games and other events
    for e in ev_today.itertuples():
        team = team_of(e.event)
        days = set(past_ev[past_ev.event.map(team_of) == team].date)
        mask = hist.business_date.isin(days)
        m = measure(hist, mask, dow, without=~event_days)
        sh = float(e.start_hour) if e.start_hour is not None and e.start_hour == e.start_hour else None
        kind = "game" if team in GAME_TEAMS else "event"
        if m["effect"] is None:
            lift = float(e.lift) if getattr(e, "lift", None) is not None and e.lift == e.lift else None
            m = {**m, "effect": (lift - 1) if lift else None}
            why = (f"{e.event}: no past examples in the last year; using the events table's planned "
                   f"{_pct(m['effect']):+.0f}%." if lift else f"{e.event}: no past examples; effect unknown.")
            out.append(_driver(kind, str(e.event), m, why, time=_clock(sh) if sh is not None else None,
                               extra={"no_history": True, "venue": getattr(e, "venue", None)}))
            continue
        window, note, wl = None, None, None
        if sh is not None:
            h0, h1 = max(sh - 0.5, 11.0), min(sh + 2.5, B.close_bin(date) / 4)
            window = {"start": _clock(h0), "end": _clock(h1)}
            pool = hist if m["estimate"] else hist[hist.dow == dow]
            wd = [B.ddate(x) for x in pool[mask.loc[pool.index]].business_date]
            wo = [B.ddate(x) for x in pool[(~event_days).loc[pool.index]].business_date][-26:]
            wl, note = _window_effect(wd, wo, h0, h1, db)
        where = f"on {dn}s" if not m["estimate"] else "on any weekday (few same-weekday examples)"
        verb = GAME_TEAMS.get(team, "the start")
        why = (f"{m['n']} past {team} home games {where} averaged {_pct(m['effect']):+.1f}% orders vs event-free days"
               + (f"; {_pct(wl):+.0f}% in the {window['start']}-{window['end']} window" if wl is not None else "")
               + (f", {note} after {verb}" if note else "") + ".")
        out.append(_driver(kind, str(e.event), m, why, time=_clock(sh) if sh is not None else None, window=window,
                           channel_note=note, extra={"window_effect_pct": _pct(wl) if wl is not None else None,
                                                     "venue": getattr(e, "venue", None)}))

    # ---- weather
    if not weather_known:
        t = cal.get("temp_high_c")
        out.append(_driver("weather", "Weather not known yet", {"effect": 0.0, "estimate": True},
                           weather_note or (f"More than a day out: the forecast assumes seasonal-normal weather"
                                            + (f" ({t:.0f}°C high, dry)." if t is not None else "."))))
    else:
        dry = ~hist.rain & ~hist.snow
        for key, label, adj in (("snow", "Snow", "Snowy"), ("rain", "Rain", "Rainy")):
            if cal.get(key):
                m = measure(hist, hist[key], dow, without=dry)
                if m["effect"] is None:
                    continue
                note = None
                if not m["estimate"]:
                    wd = [B.ddate(x) for x in hist[(hist.dow == dow) & hist[key]].business_date]
                    wo = [B.ddate(x) for x in hist[(hist.dow == dow) & dry].business_date][-26:]
                    _, note = _window_effect(wd, wo, 11, 23, db)
                why = (f"{m['n']} {adj.lower()} {dn}s averaged {_pct(m['effect']):+.1f}% orders vs dry {dn}s"
                       if not m["estimate"] else f"{adj} days averaged {_pct(m['effect']):+.1f}% vs their weekday's dry normal")
                eve = bool(cal.get("evening_rain")) and key == "rain"
                out.append(_driver("weather", "Rain this evening" if eve else label, m, why + (f" ({note})." if note else "."),
                                   channel_note=note, time="17:00" if eve else None))
                break  # snow days are also wet: one precipitation driver
        t = cal.get("temp_high_c")
        if t is not None and (t < COLD_C or t > HOT_C):
            cold = t < COLD_C
            mask = hist.temp_high_c < COLD_C if cold else hist.temp_high_c > HOT_C
            m = measure(hist, mask, dow)
            if m["effect"] is not None:
                lbl = f"{'Cold' if cold else 'Hot'} ({t:.0f}°C)"
                out.append(_driver("weather", lbl, m, f"{dn}s {'below' if cold else 'above'} {COLD_C if cold else HOT_C:.0f}°C "
                                   f"averaged {_pct(m['effect']):+.1f}% orders" + (" (few examples)." if m["estimate"] else ".")))

    # ---- holiday (one example a year: the calendar's planned multiplier)
    hol = cal.get("holiday")
    if isinstance(hol, str) and hol:
        hf = float(cal.get("holiday_factor") if cal.get("holiday_factor") is not None else 1.0)
        out.append(_driver("holiday", hol, {"effect": hf - 1, "estimate": True, "n": 1},
                           "Closed." if hf == 0 else "Each holiday comes once a year, so this uses the calendar's planned multiplier."))

    # ---- universities on break
    if cal.get("school_in_session") is not None and not bool(cal.get("school_in_session")):
        m = measure(hist, ~hist.school_in_session, dow)
        if m["effect"] is not None:
            out.append(_driver("school", "CMU/Pitt on break", m,
                               f"{m['n']} {dn}s during university breaks averaged {_pct(m['effect']):+.1f}% orders vs term-time {dn}s."
                               if not m["estimate"] else f"Break days averaged {_pct(m['effect']):+.1f}% vs their weekday's term-time normal."))

    # ---- DoorDash promo
    if cal.get("dd_promo"):
        m = measure(hist, hist.dd_promo, dow)
        if m["effect"] is not None:
            pool = hist if m["estimate"] else hist[hist.dow == dow]
            _, note = _window_effect([B.ddate(x) for x in pool[pool.dd_promo].business_date],
                                     [B.ddate(x) for x in pool[~pool.dd_promo].business_date][-26:], 11, 23, db)
            out.append(_driver("promo", "DoorDash promo", m, f"{m['n']} promo days averaged {_pct(m['effect']):+.1f}% orders"
                               + (f" vs other {dn}s" if not m["estimate"] else " vs their weekday's normal")
                               + (f" ({note})." if note else "."), channel_note=note))

    # ---- weekday
    wk = hist.groupby("dow").orders.mean()
    if dow in wk.index:
        m = {"effect": float(wk[dow] / wk.mean() - 1), "n": int((hist.dow == dow).sum()), "n_without": int(len(hist)),
             "estimate": False, "evidence": [B.ddate(x) for x in hist[hist.dow == dow].business_date.sort_values(ascending=False)]}
        out.append(_driver("weekday", dn, m, f"{dn}s averaged {wk[dow]:.0f} orders, {_pct(m['effect']):+.1f}% vs the average open day."))

    # ---- trend: last 4 weeks vs the 4 before, weekday for weekday
    last = hist[hist.business_date > d - pd.Timedelta(days=28)]
    prev = hist[(hist.business_date <= d - pd.Timedelta(days=28)) & (hist.business_date > d - pd.Timedelta(days=56))]
    if len(last) >= 10 and len(prev) >= 10:
        rel = lambda x: float((x.orders / x.dow.map(wk)).mean())  # noqa: E731
        m = {"effect": rel(last) / rel(prev) - 1, "n": int(len(last)), "n_without": int(len(prev)), "estimate": False,
             "evidence": [B.ddate(x) for x in last.business_date.sort_values(ascending=False)]}
        out.append(_driver("trend", "Recent trend", m, f"The last 4 weeks ran {_pct(m['effect']):+.1f}% vs the 4 weeks before, weekday for weekday."))

    out.sort(key=lambda x: -abs(x["effect_pct"]))
    return out
