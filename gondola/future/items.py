"""Limited items: Chashu, Ajitama egg, Gyoza, Tonkotsu broth.

Which dishes use each item and how much comes from the recipes table (data/raw/recipes.csv); units and hold days
from the skus table. Usage per order is learned from history (recipes x item mix / completed orders) on the
reference days, skipping days chashu sold out (a sell-out cancels ramen orders, which under-counts every item).

Item demand per 15 minutes = the order forecast curve x usage per order. The prep target is a newsvendor on the
day forecast's range (chashu: the existing plan.newsvendor_par, unchanged; the others: the same rule with their own
costs). Pause times per app reuse plan.pause_times (DoorDash 2, Uber Eats 2, Grubhub 10 minutes to take effect, so
Grubhub is paused first). Busy-night times use the P90/P50 x 1.1 curve, as the close pipeline does.

Only chashu has a prep log. For the others, what was prepped today is the kitchen's habit: the average use on the
last 4 same weekdays x 1.10, rounded up to the batch (`habit_prep`). Item costs/margins are configuration
assumptions, not measured.
"""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.stats import norm

from ..metrics import Store
from ..tools import plan
from . import base as B
from .base import DB, hm

# key = sku in recipes/skus. cost: $ per unit. margin: $ lost per unit short. leftover_value: share of a leftover
# still usable tomorrow. score_share: share of shortfalls that hit the DoorDash score (cancellations).
ITEMS = [
    {"key": "chashu", "name": "Chashu", "batch": 10, "recount_at": 120, "buffer": 8, "cost": plan.CHASHU_COST,
     "margin": plan.CHASHU_MARGIN, "leftover_value": 0.6, "score_share": 0.4, "prep_task": "Braise chashu"},
    {"key": "ajitama_egg", "name": "Ajitama egg", "batch": 30, "recount_at": 100, "buffer": 8, "cost": 0.42,
     "margin": 2.0, "leftover_value": 0.7, "score_share": 0.1, "prep_task": "Marinate eggs"},
    {"key": "gyoza", "name": "Gyoza", "batch": 60, "recount_at": 120, "buffer": 18, "cost": 0.28,
     "margin": 1.0, "leftover_value": 0.9, "score_share": 0.2, "prep_task": "Fold gyoza"},
    {"key": "tonkotsu_broth", "name": "Tonkotsu broth", "batch": 10, "recount_at": 40, "buffer": 4, "cost": 1.10,
     "margin": 26.0, "leftover_value": 0.7, "score_share": 0.4, "prep_task": "Tonkotsu broth"},
]
KEYS = [i["key"] for i in ITEMS]
HABIT_WEEKS = 4
HABIT_MARGIN = 1.10


def _cfg(db=DB) -> dict:
    def load():
        st = Store(db)
        rec = st.df("SELECT item, sku, qty FROM recipes WHERE sku IN (SELECT unnest(?::VARCHAR[]))", [KEYS])
        sk = st.df("SELECT sku, unit, shelf_life_days FROM skus WHERE sku IN (SELECT unnest(?::VARCHAR[]))", [KEYS]).set_index("sku")
        return {"recipes": rec, "skus": sk}
    return B.CACHE.get(("items_cfg", str(db), B.db_version(db)), load)


def limited_items(db=DB) -> list[dict]:
    """Future -> Present/Review contract: [{key, name, sku, unit, used_by:{menu_item: qty}, batch, hold_days,
    recount_at, buffer}] (Chashu, Ajitama egg, Gyoza, Tonkotsu broth)."""
    c = _cfg(db)
    out = []
    for it in ITEMS:
        r = c["recipes"][c["recipes"].sku == it["key"]]
        sk = c["skus"].loc[it["key"]] if it["key"] in c["skus"].index else None
        out.append({"key": it["key"], "name": it["name"], "sku": it["key"],
                    "unit": str(sk.unit) if sk is not None else "unit",
                    "used_by": {str(a): float(q) for a, q in zip(r.item, r.qty)},
                    "batch": it["batch"], "hold_days": int(sk.shelf_life_days) if sk is not None else 1,
                    "recount_at": it["recount_at"], "buffer": it["buffer"]})
    return out


def _item(key: str) -> dict:
    return next(i for i in ITEMS if i["key"] == key)


# ------------------------------------------------------------------ usage
def usage_by_day(store: Store, dates: list[str] | None = None, date: str | None = None) -> pd.DataFrame:
    """Units used per business day per item from completed orders x recipes: (business_date, sku, used, orders).
    Pass `date` with a cut store for today so far."""
    ds = [date] if date else dates
    q = """WITH r AS (SELECT item, sku, qty FROM recipes WHERE sku IN (SELECT unnest(?::VARCHAR[]))),
                n AS (SELECT business_date, COUNT(*) orders FROM orders WHERE status='completed'
                      AND business_date IN (SELECT unnest(?::DATE[])) GROUP BY 1)
           SELECT o.business_date, r.sku, SUM(r.qty) used, any_value(n.orders) orders
           FROM orders o JOIN order_lines l USING(order_id) JOIN r ON r.item = l.item JOIN n USING(business_date)
           WHERE o.status='completed' AND o.business_date IN (SELECT unnest(?::DATE[])) GROUP BY 1, 2"""
    return store.df(q, [KEYS, ds, ds])


def reference_days(store: Store, dates: list[str]) -> list[str]:
    """`dates` without chashu sell-out days (kept if fewer than 2 would remain), as plan does for chashu."""
    clean = store.df("SELECT business_date FROM prep_log WHERE NOT sold_out AND business_date IN (SELECT unnest(?::DATE[]))", [dates])
    return [B.ddate(d) for d in clean.business_date] if len(clean) >= 2 else list(dates)


def usage_per_order(store: Store, dates: list[str]) -> dict[str, float]:
    """Units per completed order per item on the reference days. Chashu uses plan.chashu_portions_per_order
    (identical to the close pipeline)."""
    ref = reference_days(store, dates)
    u = usage_by_day(store, ref)
    out = {}
    for k in KEYS:
        if k == "chashu":
            r = plan.chashu_portions_per_order(store, dates)
            out[k] = float(np.mean(r)) if len(r) else 0.0
        else:
            x = u[u.sku == k]
            out[k] = float((x.used / x.orders).mean()) if len(x) else 0.0
    return out


def habit_prep(store: Store, key: str, date: str) -> float:
    """What the kitchen made on `date`: chashu from the prep log; others from habit (average use on the last 4
    same weekdays before `date` x 1.10, rounded up to the batch)."""
    it = _item(key)
    if key == "chashu":
        p = store.df("SELECT par FROM prep_log WHERE business_date = ?", [B.ddate(date)])
        if len(p):
            return float(p.par[0])
    d = pd.Timestamp(date)
    past = [B.ddate(d - pd.Timedelta(days=7 * k)) for k in range(1, 9)]
    u = usage_by_day(store, past)
    u = u[(u.sku == key) & (u.used > 0)].sort_values("business_date", ascending=False).head(HABIT_WEEKS)
    if u.empty:
        return 0.0
    return float(math.ceil(u.used.mean() * HABIT_MARGIN / it["batch"]) * it["batch"])


# ------------------------------------------------------------------ prep target and card
def newsvendor(key: str, p10: float, p50: float, p90: float, upo: float) -> dict:
    """Units to have: chashu = plan.newsvendor_par (unchanged); others the same lognormal newsvendor with their costs."""
    if key == "chashu":
        nv = plan.newsvendor_par(p10, p50, p90, upo)
        return {"critical_ratio": nv["critical_ratio"], "orders_planned": nv["orders_planned"], "target": nv["chashu_portions"]}
    it = _item(key)
    cu = it["margin"] + plan.SCORE_RISK * it["score_share"]
    co = it["cost"] * (1 - it["leftover_value"])
    ratio = cu / (cu + co)
    sigma = (np.log(p90) - np.log(p10)) / (2 * 1.2816)
    q = float(np.exp(np.log(p50) + sigma * norm.ppf(ratio)))
    q = min(q, p90 * 1.05)
    return {"critical_ratio": round(ratio, 3), "orders_planned": round(q, 1),
            "target": int(math.ceil(q * upo / it["batch"]) * it["batch"])}


def _recount_time(curve: list[dict], have: float, upo: float, at: float) -> str | None:
    if have <= at:
        return curve[0]["time"] if curve else None
    cum = 0.0
    for c in curve:
        cum += c["orders"] * upo
        if have - cum <= at:
            return c["time"]
    return None


def card(key: str, target: int, leftover: float, curve: list[dict], upo: float, busy_ratio: float = 1.0) -> dict:
    """One item's card. Chashu is exactly plan.close_card plus key/unit fields."""
    it = _item(key)
    unit = next((x["unit"] for x in limited_items() if x["key"] == key), "unit")
    if key == "chashu":
        c = plan.close_card("Chashu", target, leftover, curve, upo, busy_ratio=busy_ratio)
    else:
        try:
            usable = float(leftover or 0)
        except (TypeError, ValueError):
            usable = 0.0
        warnings = []
        if usable != usable or usable < 0:
            warnings.append("leftover count looked wrong; ignored it"); usable = 0.0
        if usable > target:
            warnings.append(f"leftover ({usable:.0f}) is more than tomorrow needs ({target}); check the count")
        usable = min(usable, target)
        make = max(int(math.ceil((target - usable) / it["batch"]) * it["batch"]), 0)
        c = {"item": it["name"], "target": target, "on_hand": round(usable, 1), "prep": make,
             "pause_at": plan.pause_times(curve, make + usable, upo, it["buffer"]),
             "pause_if_busy": plan.pause_times([{**x, "orders": x["orders"] * busy_ratio} for x in curve], make + usable, upo, it["buffer"]),
             "recount_at": it["recount_at"], "warnings": warnings}
    have = c["prep"] + c["on_hand"]
    return {**c, "key": key, "unit": unit, "batch": it["batch"], "buffer": it["buffer"], "per_order": round(upo, 3),
            "recount_time": _recount_time(curve, have, upo, c["recount_at"])}


def close_cards(store: Store, fc: dict, leftovers: dict | None = None, keys: list[str] | None = None) -> list[dict]:
    """Cards for the forecast day `fc` (needs p10/p50/p90, curve, similar_days), chashu first. leftovers:
    {key: units on hand}. A closed day (p50 <= 0) has no cards."""
    if fc.get("p50", 0) <= 0:
        return []
    leftovers = leftovers or {}
    sims = [s["date"] for s in fc["similar_days"]]
    upo = usage_per_order(store, sims)
    busy = fc["p90"] / fc["p50"] * 1.1
    out = []
    for k in keys or KEYS:
        if upo.get(k, 0) <= 0:
            continue
        nv = newsvendor(k, fc["p10"], fc["p50"], fc["p90"], upo[k])
        out.append({**card(k, nv["target"], leftovers.get(k, 0), fc["curve"], upo[k], busy), "critical_ratio": nv["critical_ratio"]})
    return out


def extra_cards(store: Store, fc: dict, leftovers: dict | None = None) -> list[dict]:
    """For the close pipeline: the cards for every limited item except chashu (which the pipeline already makes)."""
    return close_cards(store, fc, leftovers, keys=[k for k in KEYS if k != "chashu"])


# ------------------------------------------------------------------ today: what's left and when it runs out
def runout(date: str, now: datetime | None = None, db=DB) -> list[dict]:
    """Future -> Present/Review contract: [{key, believed_left, projected_runout:"HH:MM"|None, pause_at:{doordash,
    ubereats, grubhub}}] for `date` at `now` (store clock if None), plus name/unit/prep/sold/recount fields.
    believed_left = prepped (prep log or habit) - used by completed orders so far. Projection follows the nowcast's
    rest-of-day P50 (pause_if_busy: its P90)."""
    from .nowcast import nowcast
    date = B.ddate(date)
    nc = nowcast(date, now, db)
    m = nc["minute"]
    st = B.store_at(date, m, db)
    st0 = B.store_at(date, 0, db)
    sims = [s["date"] for s in nc["morning"]["similar_days"]]
    upo = usage_per_order(st0, sims)
    used = usage_by_day(st, date=date) if m > 0 else pd.DataFrame(columns=["sku", "used"])
    rb = nc["rest_bins"]
    curve = B.curve_from_bins(rb, "p50") if len(rb) else []
    busy = B.curve_from_bins(rb, "p90") if len(rb) else []
    cfg = {x["key"]: x for x in limited_items(db)}
    out = []
    for it in ITEMS:
        k = it["key"]
        prep = habit_prep(st0, k, date)
        sold = float(used[used.sku == k].used.sum()) if len(used) else 0.0
        left = prep - sold
        u = upo.get(k, 0.0)
        cum, proj = 0.0, None
        for c in curve:
            cum += c["orders"] * u
            if left - cum <= 0:
                proj = c["time"]; break
        if left <= 0 and curve:
            proj = curve[0]["time"]
        now_t = hm(m // 15 * 15)
        pause = plan.pause_times(curve, left, u, it["buffer"]) if curve else {a: None for a in B.APPS}
        pause_busy = plan.pause_times(busy, left, u, it["buffer"]) if busy else {a: None for a in B.APPS}
        if curve and left <= it["buffer"]:
            pause = {a: now_t for a in pause}
        out.append({"key": k, "name": it["name"], "unit": cfg[k]["unit"], "prep": round(prep, 1),
                    "prep_source": "prep_log" if k == "chashu" and _has_log(st0, date) else "habit",
                    "sold": round(sold, 1), "believed_left": round(left, 1), "projected_runout": proj,
                    "pause_at": pause, "pause_if_busy": pause_busy, "per_order": round(u, 3),
                    "recount_at": it["recount_at"], "recount_time": _recount_time(curve, left, u, it["recount_at"]) if curve else None,
                    "rest_of_day_need": round(sum(c["orders"] for c in curve) * u, 1)})
    return out


def _has_log(st: Store, date: str) -> bool:
    return len(st.df("SELECT 1 FROM prep_log WHERE business_date = ?", [date])) > 0
