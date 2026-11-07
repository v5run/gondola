"""Analyst Agent tools: how did today go, and why?"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..metrics import Store

FEATURES = ["dow", "rain", "snow", "temp_high_c", "event_lift", "penguins", "steelers", "school_in_session",
            "dd_promo", "holiday_factor"]


def _feat(df: pd.DataFrame) -> np.ndarray:
    X = df[FEATURES].astype(float).values.copy()
    X[:, 0] = 0  # weekday handled by hard filter + weight
    scale = np.array([1, 1.5, 2, 1 / 6, 8, 1.2, 1.5, 1, 1, 3])
    return X * scale


def find_similar_days(store: Store, date: str, k: int = 5, daily: pd.DataFrame | None = None) -> list[dict]:
    """Nearest past days by weekday, weather, events, school, promos and holidays (only days before `date`)."""
    df = daily if daily is not None else store.daily_frame()
    target = df[df.business_date == pd.Timestamp(date)]
    if target.empty:
        cal = store.df("SELECT * FROM calendar WHERE date = ?", [date]).rename(columns={"date": "business_date"})
        ev = store.df("SELECT max(lift) l, max(CASE WHEN event LIKE 'Penguins%' THEN 1 ELSE 0 END) p, "
                      "max(CASE WHEN event LIKE 'Steelers%' THEN 1 ELSE 0 END) s FROM events WHERE date = ?", [date])
        cal["event_lift"] = ev.l.fillna(1.0)[0] if len(ev) and ev.l[0] is not None else 1.0
        cal["penguins"] = ev.p.fillna(0)[0] if len(ev) and ev.p[0] is not None else 0
        cal["steelers"] = ev.s.fillna(0)[0] if len(ev) and ev.s[0] is not None else 0
        target = cal
    past = df[(df.business_date < pd.Timestamp(date)) & (df.orders > 0)].copy()
    t = target.iloc[0]
    same = past[past.dow == t.dow]
    pool = same if len(same) >= k else past
    dist = np.linalg.norm(_feat(pool) - _feat(target.iloc[[0]]), axis=1)
    # recency: prefer recent weeks slightly (store grows)
    age = (pd.Timestamp(date) - pool.business_date).dt.days.values / 365
    pool = pool.assign(distance=dist + 0.6 * age).nsmallest(k, "distance")
    return [{"date": str(r.business_date.date()), "orders": int(r.orders), "net_sales": round(float(r.net_sales), 2),
             "why": ", ".join(x for x in [
                 "same weekday" if r.dow == t.dow else None,
                 "rain" if r.rain and t.rain else None,
                 "Penguins game" if r.penguins and t.penguins else None,
                 "Steelers game" if r.steelers and t.steelers else None,
                 "school in session" if r.school_in_session and t.school_in_session else None] if x),
             "distance": round(float(r.distance), 3)} for r in pool.itertuples()]


def usual_weekdays(daily: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    """Up to four prior, non-holiday service days on the same weekday."""
    return daily[(daily.business_date < date) & (daily.dow == date.day_of_week)
                 & (daily.orders > 0) & (daily.holiday_factor == 1)].tail(4)


def compare_periods(store: Store, date: str, baseline: str = "usual_weekday", daily: pd.DataFrame | None = None) -> dict:
    """Today vs the average of the last 4 same weekdays (or similar days)."""
    df = daily if daily is not None else store.daily_frame()
    d = pd.Timestamp(date)
    today = df[df.business_date == d]
    if today.empty or float(today.orders.iloc[0]) == 0:
        return {"date": date, "status": "no_data", "baseline_dates": []}
    t = today.iloc[0]
    if baseline == "similar_days":
        sims = [pd.Timestamp(x["date"]) for x in find_similar_days(store, date, 5, df)]
        base = df[df.business_date.isin(sims)]
    else:
        base = usual_weekdays(df, d)
    out = {"date": date, "baseline": baseline, "baseline_dates": [str(x.date()) for x in base.business_date]}
    if base.empty or float(t.orders) == 0:
        out["status"] = "no_data" if float(t.orders) == 0 else "no_baseline"
    for m in ("orders", "net_sales", "avg_ticket", "labour_pct", "cancels", "avoidable_cancels"):
        b = float(base[m].mean())
        v = float(t[m])
        out[m] = {"value": round(v, 4) if v == v else None, "baseline": round(b, 4) if b == b else None,
                  "change_pct": round((v - b) / b, 4) if (b and b == b and v == v) else None}
    return out


def explain_change(store: Store, date: str, daily: pd.DataFrame | None = None, cp: dict | None = None) -> dict:
    """Break the change vs a usual weekday into channels and dayparts. daily / cp: precomputed daily frame and
    compare_periods result (optional, to avoid recomputing them)."""
    d = pd.Timestamp(date)
    cp = cp or compare_periods(store, date, daily=daily)
    if cp.get("status") == "no_data":
        cal = store.df("SELECT holiday FROM calendar WHERE date = ?", [date])
        h = cal.holiday[0] if len(cal) and cal.holiday[0] is not None and not pd.isna(cal.holiday[0]) else None
        return {"status": "no_data", "channel": [], "daypart": [], "context": {"rain": False, "snow": False, "events": [h] if h else [], "closed": True}}
    base_dates = cp["baseline_dates"]
    q = """SELECT business_date, channel,
                  CASE WHEN extract(hour FROM created_at) < 15 THEN 'lunch'
                       WHEN extract(hour FROM created_at) < 21 THEN 'dinner' ELSE 'late' END AS daypart,
                  SUM(subtotal) sales, COUNT(*) n
           FROM orders WHERE status='completed' AND business_date IN (SELECT unnest(?::DATE[])) GROUP BY 1,2,3"""
    x = store.df(q, [[date] + base_dates])
    x["is_today"] = x.business_date == d
    nb = max(len(base_dates), 1)
    res = {}
    for dim in ("channel", "daypart"):
        today = x[x.is_today].groupby(dim).sales.sum()
        base = x[~x.is_today].groupby(dim).sales.sum() / nb
        diff = (today - base).fillna(0).sort_values()
        res[dim] = [{"key": k, "today": round(float(today.get(k, 0)), 2), "usual": round(float(base.get(k, 0)), 2),
                     "change": round(float(v), 2)} for k, v in diff.items()]
    ctx = store.df("SELECT * FROM calendar WHERE date = ?", [date]).iloc[0]
    ev = store.df("SELECT event FROM events WHERE date = ?", [date]).event.tolist()
    so = store.df("SELECT sold_out FROM prep_log WHERE business_date = ?", [date])
    canc = store.df("SELECT COUNT(*) n FROM orders WHERE business_date = ? AND cancel_reason = 'item_unavailable'", [date]).n[0]
    if len(so) and bool(so.sold_out[0]):
        ev = ev + [f"chashu sold out ({int(canc)} app orders cancelled)"]
    if isinstance(ctx.holiday, str):
        ev = [ctx.holiday] + ev
    if not bool(ctx.school_in_session):
        ev = ev + ["CMU/Pitt on break"]
    res["context"] = {"rain": bool(ctx.rain), "snow": bool(ctx.snow), "temp_high_c": float(ctx.temp_high_c), "events": ev}
    return res


def rush_curve(store: Store, date: str) -> pd.DataFrame:
    q = """SELECT time_bucket(INTERVAL 15 MINUTE, created_at) AS bin, COUNT(*) n FROM orders
           WHERE business_date = ? GROUP BY 1 ORDER BY 1"""
    return store.df(q, [date])


def item_mix(store: Store, date: str) -> pd.DataFrame:
    q = """SELECT l.item, COUNT(*) sold, SUM(l.price) sales FROM orders o JOIN order_lines l USING(order_id)
           WHERE o.business_date = ? AND o.status='completed' GROUP BY 1 ORDER BY 2 DESC"""
    return store.df(q, [date])
