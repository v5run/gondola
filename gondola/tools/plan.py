"""Plan Agent tools: what should we do about tomorrow?

prep par: newsvendor on the forecast distribution, with the cost of running out including the
DoorDash score risk (an avoidable cancellation), not only lost margin.
prep timing and staffing: OR-Tools CP-SAT.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

CHASHU_COST = 7.80 / 7.0          # $ per portion (pork belly cost / yield)
CHASHU_MARGIN = 11.0               # lost contribution per chashu dish not sold
SCORE_RISK = 6.0                   # $ equivalent of one avoidable cancellation on DoorDash
CHASHU_HOLD_DAYS = 3


def chashu_portions_per_order(store, dates: list[str]) -> np.ndarray:
    """Learned from days that did NOT sell out (sell-out days under-count demand)."""
    clean = store.df("SELECT business_date FROM prep_log WHERE NOT sold_out AND business_date IN (SELECT unnest(?::DATE[]))", [dates])
    if len(clean) >= 2:
        dates = [str(pd.Timestamp(d).date()) for d in clean.business_date]
    q = """SELECT o.business_date, SUM(m.chashu_portions) / COUNT(DISTINCT o.order_id) AS r
           FROM orders o JOIN order_lines l USING(order_id) JOIN menu m ON m.item = l.item
           WHERE o.status='completed' AND o.business_date IN (SELECT unnest(?::DATE[])) GROUP BY 1"""
    return store.df(q, [dates]).r.values


def newsvendor_par(p10: float, p50: float, p90: float, portions_per_order: float, leftover_value: float = 0.6) -> dict:
    """Choose chashu portions. Underage: margin + score risk. Overage: cost x (1 - share usable tomorrow)."""
    cu = CHASHU_MARGIN + SCORE_RISK * 0.4  # ~40% of chashu demand comes through DoorDash
    co = CHASHU_COST * (1 - leftover_value)
    ratio = cu / (cu + co)
    # lognormal fitted to the P10/P90 range
    sigma = (np.log(p90) - np.log(p10)) / (2 * 1.2816)
    mu = np.log(p50)
    from scipy.stats import norm
    q_orders = float(np.exp(mu + sigma * norm.ppf(ratio)))
    q_orders = min(q_orders, p90 * 1.05)  # cap: never prep for more than the high end
    par = int(np.ceil(q_orders * portions_per_order / 10) * 10)
    return {"critical_ratio": round(ratio, 3), "orders_planned": round(q_orders, 1), "chashu_portions": par}


def prep_schedule(tasks: list[dict], cooks: int = 2, day_start: int = 9 * 60, horizon: int = 18 * 60) -> list[dict]:
    """tasks: {name, minutes, deadline (minutes from midnight), needs (optional task name)}."""
    m = cp_model.CpModel()
    iv, st, en = {}, {}, {}
    for t in tasks:
        s = m.NewIntVar(day_start, horizon, f"s_{t['name']}")
        e = m.NewIntVar(day_start, horizon, f"e_{t['name']}")
        iv[t["name"]] = m.NewIntervalVar(s, t["minutes"], e, f"i_{t['name']}")
        st[t["name"]], en[t["name"]] = s, e
        m.Add(e <= t["deadline"])
    for t in tasks:
        if t.get("needs"):
            m.Add(st[t["name"]] >= en[t["needs"]])
    m.AddCumulative(list(iv.values()), [1] * len(iv), cooks)
    m.Minimize(sum(en.values()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return [{"name": t["name"], "status": "infeasible"} for t in tasks]
    fmt = lambda x: f"{x//60}:{x%60:02d}"
    return sorted([{"name": t["name"], "start": fmt(solver.Value(st[t["name"]])), "end": fmt(solver.Value(en[t["name"]])),
                    "deadline": fmt(t["deadline"]), "_s": solver.Value(st[t["name"]])} for t in tasks], key=lambda r: r.pop("_s") if False else r["_s"])


def staff_gaps(curve: list[dict], scheduled: dict[str, int], orders_per_cook_15: float = 7.5) -> list[dict]:
    """Compare forecast orders per 15 minutes with kitchen capacity from the schedule (cooks per hour)."""
    gaps = []
    for c in curve:
        hour = c["bin"] // 4
        cooks = scheduled.get(hour, 0)
        cap = cooks * orders_per_cook_15
        if c["orders"] > cap * 1.0 and c["orders"] > 3:
            gaps.append({"time": c["time"], "forecast": c["orders"], "capacity": cap,
                         "extra_cooks": int(np.ceil((c["orders"] - cap) / orders_per_cook_15))})
    # merge consecutive bins
    merged = []
    for g in gaps:
        if merged and _mins(g["time"]) - _mins(merged[-1]["end"]) <= 0:
            merged[-1]["end"] = _add15(g["time"]); merged[-1]["extra_cooks"] = max(merged[-1]["extra_cooks"], g["extra_cooks"])
        else:
            merged.append({"start": g["time"], "end": _add15(g["time"]), "extra_cooks": g["extra_cooks"]})
    return merged


def _mins(t: str) -> int:
    h, m = t.split(":"); return int(h) * 60 + int(m)


def _add15(t: str) -> str:
    x = _mins(t) + 15; return f"{x//60:02d}:{x%60:02d}"


def safety_net_rule(curve: list[dict], par: int, portions_per_order: float, buffer_orders: float = 6) -> dict:
    """When will chashu run out if demand follows the forecast? Pause chashu on the apps a few orders early."""
    cum = 0.0
    for c in curve:
        cum += c["orders"] * portions_per_order
        if cum >= par - buffer_orders * portions_per_order:
            return {"item_group": "chashu", "pause_apps_at": c["time"], "keep_in_store": True,
                    "trigger": f"or when fewer than {int(buffer_orders * portions_per_order)} portions remain"}
    return {"item_group": "chashu", "pause_apps_at": None, "trigger": "only if fewer than "
            f"{int(buffer_orders * portions_per_order)} portions remain"}


# How long each app takes to act on a pause (minutes). DoorDash/Uber via item-status API; Grubhub via a prompt the
# manager taps, so it needs more lead time.
PAUSE_DELAY_MIN = {"doordash": 2, "ubereats": 2, "grubhub": 10}
RECOUNT_AT = 120  # portions believed left: when Gondola asks the line for a quick count


def pause_times(curve: list[dict], have: float, portions_per_order: float, buffer_portions: float = 8,
                app_share: float = 0.66) -> dict:
    """Predicted pause time per app: the moment forecast portions left reach the buffer plus what the apps sell
    while the pause takes effect."""
    out = {}
    for app, delay in PAUSE_DELAY_MIN.items():
        cum, t = 0.0, None
        for i, c in enumerate(curve):
            rate = c["orders"] * portions_per_order / 15  # portions per minute in this slot
            need_buffer = buffer_portions + rate * app_share * delay
            cum += c["orders"] * portions_per_order
            if have - cum <= need_buffer:
                t = c["time"]; break
        out[app] = t
    return out


def close_card(item: str, target: int, leftover: float, curve: list[dict], ppo: float, busy_ratio: float = 1.0) -> dict:
    """Tomorrow's card for one limited item: what to prep, and when each app will be paused if demand follows
    the forecast. The manager approves it at close."""
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
    make = max(int(np.ceil((target - usable) / 10) * 10), 0)
    return {"item": item, "target": target, "on_hand": round(usable, 1), "prep": make,
            "pause_at": pause_times(curve, make + usable, ppo),
            "pause_if_busy": pause_times([{**c, "orders": c["orders"] * busy_ratio} for c in curve], make + usable, ppo),
            "recount_at": RECOUNT_AT, "warnings": warnings}
