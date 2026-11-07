"""Horizon: day forecasts from tomorrow up to 7 days ahead.

One LightGBM day model (the same features and parameters as tools/demand) is trained on every complete day up to
today. Each future day gets a calendar row: tomorrow's comes from the calendar table (weather known); later days
keep the calendar's holiday / school / promo flags when the table has them (else carried forward, with holidays
from fixed rules) and use the seasonal-normal weather (mean high of past days within 10 days of the same day of
the year, dry): weather_known False. Events come from the events table. Lags are recursive: each day's P50 stands
in for its orders in later days' lag features. Ranges: the split-conformal ratios (backtested night-before errors
of the 60 days before tomorrow) widened by sqrt(horizon) in log space.

With GONDOLA_WEATHER=openmeteo the live feed (future/weather.py) supplies weather for the days it covers
(weather_known True, source open-meteo); any failure falls back to the above.
"""
from __future__ import annotations

from datetime import date as Date, datetime, timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd

from ..metrics import Store
from ..tools import demand
from ..tools.analyst import find_similar_days
from . import base as B
from . import drivers as DR
from . import items as IT
from . import weather as W
from .base import DB

MAX_HORIZON = 7
_COLS = ["business_date", "dow", "rain", "snow", "temp_high_c", "precip_mm", "evening_rain", "holiday", "holiday_factor",
         "school_in_session", "dd_promo", "event_lift", "penguins", "steelers", "orders"]


# ------------------------------------------------------------------ holidays past the calendar
def _nth_weekday(y: int, m: int, wd: int, n: int) -> Date:
    d = Date(y, m, 1)
    d += timedelta(days=(wd - d.weekday()) % 7)
    return d + timedelta(days=7 * (n - 1))


def _last_weekday(y: int, m: int, wd: int) -> Date:
    d = (Date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    return d - timedelta(days=(d.weekday() - wd) % 7)


def holiday_name(d: Date) -> str | None:
    """US holidays the calendar table uses, by rule (for days the table doesn't cover yet)."""
    y = d.year
    thx = _nth_weekday(y, 11, 3, 4)
    rules = {thx: "Thanksgiving", thx + timedelta(days=1): "Black Friday", Date(y, 12, 24): "Christmas Eve",
             Date(y, 12, 25): "Christmas (closed)", Date(y, 12, 31): "New Year's Eve", Date(y, 1, 1): "New Year's Day",
             Date(y, 2, 14): "Valentine's Day", _last_weekday(y, 5, 0): "Memorial Day", Date(y, 7, 4): "Independence Day",
             _nth_weekday(y, 9, 0, 1): "Labor Day"}
    return rules.get(d)


# ------------------------------------------------------------------ rows for future days
def _calendar(db) -> pd.DataFrame:
    return B.CACHE.get(("calendar", str(db), B.db_version(db)),
                       lambda: Store(db).df("SELECT * FROM calendar ORDER BY date").assign(date=lambda x: pd.to_datetime(x.date)))


def seasonal_temp(date: str, today: str, db=DB) -> float:
    cal = _calendar(db)
    cal = cal[cal.date <= pd.Timestamp(today)]
    d = pd.Timestamp(date)
    doy = cal.date.dt.dayofyear
    gap = np.minimum((doy - d.dayofyear).abs(), 365 - (doy - d.dayofyear).abs())
    near = cal[(gap <= 10) & (cal.date < pd.Timestamp(today) - pd.Timedelta(days=30))]
    return round(float(near.temp_high_c.mean() if len(near) else cal.temp_high_c.tail(14).mean()), 1)


def future_row(date: str, h: int, today: str, db=DB, live: dict | None = None) -> tuple[dict, bool, str]:
    """(calendar row, weather_known, weather source) for a day h days after today."""
    cal = _calendar(db)
    d = pd.Timestamp(date)
    hit = cal[cal.date == d]
    if len(hit):
        row = hit.iloc[0].to_dict()
    else:
        last = cal[cal.date <= pd.Timestamp(today)].iloc[-1]
        name = holiday_name(d.date())
        prev = cal[cal.holiday == name] if name else cal.iloc[0:0]
        row = {"date": d, "holiday": name, "holiday_factor": float(prev.holiday_factor.iloc[-1]) if len(prev) else 1.0,
               "school_in_session": bool(last.school_in_session), "dd_promo": False}
    row["dow"] = int(d.dayofweek)
    src, known = "calendar", True
    lw = (live or {}).get(B.ddate(date))
    if lw and lw.get("temp_high_c") is not None:
        row.update(temp_high_c=lw["temp_high_c"], precip_mm=lw["precip_mm"], rain=lw["rain"], snow=lw["snow"], evening_rain=False)
        src = "open-meteo"
    elif h > 1 or not len(hit):
        row.update(temp_high_c=seasonal_temp(date, today, db), precip_mm=0.0, rain=False, snow=False, evening_rain=False)
        src, known = "seasonal normal", False
    ev = DR._events(db)
    ev = ev[ev.date == d]
    row["event_lift"] = float(ev.lift.max()) if len(ev) else 1.0
    row["penguins"] = float(ev.event.str.startswith("Penguins").any()) if len(ev) else 0.0
    row["steelers"] = float(ev.event.str.startswith("Steelers").any()) if len(ev) else 0.0
    row["business_date"] = d
    row["orders"] = np.nan
    return row, known, src


# ------------------------------------------------------------------ the model
def _fit(upto: str, db=DB):
    """LightGBM on complete days before `upto` (same recipe as demand._fit_predict)."""
    def build():
        daily = B.daily(db, upto=upto)
        f = demand.features(daily)
        tr = f[(f.orders > 0)].dropna(subset=["lag_wk_mean"])
        m = lgb.LGBMRegressor(**demand.PARAMS)
        m.fit(tr[demand.FEATS], np.log(tr.orders / tr.holiday_factor))
        return m
    return B.CACHE.get(("hmodel", str(db), B.db_version(db), upto), build)


def predict_row(model, ext: pd.DataFrame, row: dict) -> float:
    f = demand.features(ext, pd.DataFrame([{k: row.get(k) for k in _COLS}]))
    t = f[f.business_date == row["business_date"]]
    return float(np.exp(model.predict(t[demand.FEATS]))[0] * t.holiday_factor.values[0])


def implied_effects(date: str, row: dict, now: datetime | None = None, db=DB) -> dict[str, float]:
    """How much the day model itself moves `date` for each driver feature it knows (percent): prediction with the
    row as is vs with that feature switched off. Used by the Outlook agent to avoid double counting."""
    upto = B.history_upto(date, now, db)
    model = _fit(upto, db)
    ext = B.daily(db, upto=upto)
    base = predict_row(model, ext, row)
    offs = {"rain": {"rain": False}, "snow": {"snow": False}, "penguins": {"penguins": 0.0, "event_lift": 1.0},
            "steelers": {"steelers": 0.0, "event_lift": 1.0}, "event": {"event_lift": 1.0, "penguins": 0.0, "steelers": 0.0},
            "dd_promo": {"dd_promo": False}, "school": {"school_in_session": True}}
    out = {}
    for k, ch in offs.items():
        off = predict_row(model, ext, {**row, **ch})
        out[k] = round((base / off - 1) * 100, 1) if off > 0 else 0.0
    return out


# ------------------------------------------------------------------ days
def days(start: str | None = None, n: int = MAX_HORIZON, now: datetime | None = None, db=DB, with_cards: bool = True) -> list[dict]:
    """Forecasts for n days from `start` (default tomorrow). start must be >= tomorrow; days past today+7 are
    dropped. Raises ValueError for past dates or a start beyond the horizon."""
    today = B.today_for(now, db)
    t = pd.Timestamp(today)
    tomorrow = B.ddate(t + pd.Timedelta(days=1))
    start = B.ddate(start) if start else tomorrow
    if start < tomorrow:
        raise ValueError(f"start {start} is not in the future (tomorrow is {tomorrow})")
    h0 = (pd.Timestamp(start) - t).days
    if h0 > MAX_HORIZON:
        raise ValueError(f"start {start} is more than {MAX_HORIZON} days ahead of {today}")
    n = max(0, min(int(n), MAX_HORIZON - h0 + 1))
    m_today = B.cut_minute(today, now, db)
    complete = B.today_complete(now, db)
    upto = tomorrow if complete else today
    model = _fit(upto, db)
    ext = B.daily(db, upto=upto)
    ext = ext[[c for c in _COLS if c in ext.columns]].copy()
    if not complete:  # today's lags: the nowcast's expected total
        from .nowcast import today_view
        tv = today_view(today, now, db)
        r_today, _, _ = future_row(today, 1, today, db)
        cal_today = _calendar(db)
        hit = cal_today[cal_today.date == t]
        if len(hit):
            r_today.update({k: hit.iloc[0][k] for k in ("rain", "snow", "temp_high_c", "evening_rain", "precip_mm")})
        ext = pd.concat([ext, pd.DataFrame([{**{k: r_today.get(k) for k in _COLS}, "orders": tv["expected"]["p50"]}])], ignore_index=True)
    errs = B.day_errors(tomorrow, db)
    if len(errs) >= 20:
        lo, hi = (float(x) for x in np.quantile((errs.actual / errs.predicted).values, [0.1, 0.9]))
    else:
        lo, hi = 0.8, 1.2
    live = W.daily_forecast()
    leftovers = _tonight_leftovers(today, now, db, complete) if with_cards else {}
    st = B.store_at(tomorrow, 0, db) if complete else B.store_at(today, 0, db)
    out = []
    end = h0 + n - 1
    for h in range(1, end + 1):
        dk = B.ddate(t + pd.Timedelta(days=h))
        row, known, src = future_row(dk, h, today, db, live)
        p = predict_row(model, ext, row)
        ext = pd.concat([ext, pd.DataFrame([{**{k: row.get(k) for k in _COLS}, "orders": p}])], ignore_index=True)
        if h < h0:
            continue
        adjs = B.stored_adjustments(dk)
        fac = B.adjustment_factor(adjs)
        p50 = p * fac
        s = np.sqrt(h)
        lo_h, hi_h = float(np.exp(np.log(lo) * s)), float(np.exp(np.log(hi) * s))
        drow = pd.concat([B.daily(db, upto=upto), pd.DataFrame([{**{k: row.get(k) for k in _COLS}}])], ignore_index=True)
        for c in ("rain", "snow", "school_in_session", "dd_promo"):
            drow[c] = drow[c].fillna(False).astype(bool)
        sims = find_similar_days(None, dk, 5, drow)
        shape = B.channel_shape(dk, [x["date"] for x in sims], db)
        bins = shape.assign(p50=shape.share * p50)
        curve = B.curve_from_bins(bins)
        fc = {"date": dk, "p10": round(p50 * lo_h, 1), "p50": round(p50, 1), "p90": round(p50 * hi_h, 1),
              "curve": curve, "similar_days": sims}
        rush = demand.rush_window(curve) if p50 > 0 else None
        evs = DR._events(db)
        evs = evs[evs.date == pd.Timestamp(dk)]
        drv = DR.drivers(dk, db, cal_row=row, weather_known=known, events=evs, now=now)
        cards = IT.close_cards(st, fc, leftovers if h == 1 else {}) if with_cards else []
        for c in cards:
            c["on_hand_source"] = "projected leftover tonight" if h == 1 and leftovers else "assumed 0 (not counted yet)"
        out.append({"date": dk, "horizon": h, "p10": fc["p10"], "p50": fc["p50"], "p90": fc["p90"],
                    "rush": {"start": rush["start"], "end": rush["end"], "peak_per_15min": rush["peak_per_15min"]} if rush else None,
                    "drivers": drv, "weather_known": known,
                    "weather": {"temp_high_c": B.json_safe(row.get("temp_high_c")), "rain": bool(row.get("rain")), "snow": bool(row.get("snow")),
                                "source": src},
                    "holiday": row.get("holiday") if isinstance(row.get("holiday"), str) else None,
                    "adjustments": adjs, "cards": cards,
                    "similar_days": [{k: x[k] for k in ("date", "orders", "why")} for x in sims],
                    "model": "lightgbm-daily" + (f", recursive {h} days out" if h > 1 else "") + " + similar-day shape"})
    return out


def _tonight_leftovers(today: str, now, db, complete: bool) -> dict:
    """What each item should have left after today's close: believed left now minus the rest of today's P50 need."""
    try:
        r = IT.runout(today, now, db)
    except Exception:  # noqa: BLE001
        return {}
    return {x["key"]: max(0.0, round(x["believed_left"] - (0 if complete else x["rest_of_day_need"]), 1)) for x in r}


def issue_events(rows: list[dict], today: str) -> None:
    """forecast.issued {horizon:"day"} per forecast day, keyed by the day and the date it was issued. Never raises."""
    try:
        from ..ledger import ledger
        ledger().extend([{"type": "forecast.issued", "date": today, "ts": f"{today}T00:00:00", "source": "future",
                          "key": f"forecast.issued:day:{r['date']}:{today}",
                          "payload": {"horizon": "day", "days_ahead": r["horizon"], "for_date": r["date"],
                                      "total": {k: r[k] for k in ("p10", "p50", "p90")}, "rush": r["rush"]}} for r in rows])
    except Exception:  # noqa: BLE001
        pass
