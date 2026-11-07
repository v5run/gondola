"""Guard Agent tools: keep tomorrow's service safe.

During service Guard watches portions left (prepped par minus POS sales x recipe). When fewer than
`buffer` portions remain it pauses chashu dishes on the delivery apps (keeping them for dine-in), so
app customers never order something the kitchen can't make. The pause goes through an executor with
an idempotency key; agents never call the POS directly.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from ..metrics import Store

ROOT = Path(__file__).resolve().parents[2]


class Executor:
    """Mock POS/middleware executor. Real one: Square inventory count -> 0, or middleware item availability."""

    def __init__(self, log_path: Path = ROOT / "out" / "actions_log.jsonl", fail: bool = False):
        self.log_path = log_path
        self.fail = fail
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._seen = set()
        if log_path.exists():
            for line in log_path.read_text().splitlines():
                self._seen.add(json.loads(line)["key"])

    def set_item_unavailable(self, store_id: str, date: str, item_group: str, channels: list[str], at: str) -> dict:
        key = hashlib.sha1(f"{store_id}|{date}|{item_group}|{','.join(channels)}".encode()).hexdigest()[:16]
        if key in self._seen:
            return {"status": "duplicate_ignored", "key": key}
        if self.fail:
            raise RuntimeError("POS adapter timeout")
        rec = {"key": key, "store": store_id, "date": date, "action": "set_item_unavailable", "item_group": item_group,
               "channels": channels, "at": at, "status": "ok"}
        with self.log_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        self._seen.add(key)
        return rec


def replay_day(store: Store, date: str, buffer_portions: float = 8.0) -> dict:
    """Replay one historical day with Guard on. Returns avoided cancellations and app sales held back."""
    par_row = store.df("SELECT par FROM prep_log WHERE business_date = ?", [date])
    if par_row.empty:
        return {}
    par = float(par_row.par[0])
    q = """SELECT o.order_id, o.created_at, o.channel, o.status, o.cancel_reason, o.subtotal,
                  SUM(m.chashu_portions) AS need
           FROM orders o JOIN order_lines l USING(order_id) JOIN menu m ON m.item = l.item
           WHERE o.business_date = ? GROUP BY ALL ORDER BY o.created_at"""
    o = store.df(q, [date])
    left = par
    paused_at = None
    avoided, held_back_orders, held_back_sales = 0, 0, 0.0
    for r in o.itertuples():
        if r.need <= 0:
            continue
        is_app = r.channel != "in_store"
        if paused_at is None and left < buffer_portions:
            paused_at = r.created_at
        if is_app and paused_at is not None:
            if r.status == "cancelled" and r.cancel_reason == "item_unavailable":
                avoided += 1
            elif r.status == "completed":
                held_back_orders += 1
                held_back_sales += r.subtotal
            continue
        if r.status == "completed":
            left -= r.need
    hist_cancels = int(((o.status == "cancelled") & (o.cancel_reason == "item_unavailable")).sum())
    return {"date": date, "par": par, "paused_at": str(paused_at) if paused_at is not None else None,
            "historical_avoidable_cancels": hist_cancels, "avoided": avoided,
            "app_orders_held_back": held_back_orders, "app_sales_held_back": round(held_back_sales, 2)}


def replay_year(store: Store, buffer_portions: float = 8.0) -> pd.DataFrame:
    days = store.df("SELECT business_date FROM prep_log WHERE par > 0 ORDER BY 1").business_date
    return pd.DataFrame([replay_day(store, str(pd.Timestamp(d).date()), buffer_portions) for d in days])


def check_runout(par: float, used_so_far: float, forecast_remaining_orders: float, portions_per_order: float,
                 buffer_portions: float = 8.0) -> dict:
    left = par - used_so_far
    expected_need = forecast_remaining_orders * portions_per_order
    return {"portions_left": left, "expected_need": round(expected_need, 1),
            "will_run_out": expected_need > left, "pause_apps_now": left < buffer_portions}


def guarded_day(store: Store, date: str, count_error: float = 0.0, delay_min: float = 2.0, buffer_portions: float = 8.0,
                recount_at: float = 120.0, recount: bool = True, seed: int = 0) -> dict:
    """Guard under real-world error, on one historical day: Gondola believes `par` portions were made, but the kitchen
    really has par x (1 + error). When it believes ~120 are left it asks for a quick count (off by at most 2).
    The trigger uses only the believed count; the true count is never read except to settle what happens.
    The pause reaches the apps `delay_min` later, so the buffer includes what sells in that window.
    Demand is the true (uncensored) chashu demand: served + cancelled + lost sales from data/truth."""
    import numpy as np
    rng = np.random.default_rng(seed)
    pr = store.df("SELECT par FROM prep_log WHERE business_date = ?", [date])
    if pr.empty or float(pr.par[0]) <= 0:
        return {"date": date, "cancels": 0, "held_back": 0.0, "recounts": 0, "paused_at": None, "closed": True}
    par = float(pr.par[0])
    q = """SELECT o.created_at, o.channel, SUM(m.chashu_portions) need FROM orders o JOIN order_lines l USING(order_id)
           JOIN menu m ON m.item = l.item WHERE o.business_date = ? AND m.chashu_portions > 0
           AND (o.status='completed' OR o.cancel_reason='item_unavailable') GROUP BY ALL ORDER BY 1"""
    ev = store.df(q, [date])
    ev["t"] = ev.created_at.dt.hour + ev.created_at.dt.minute / 60
    lost_p = ROOT / "data" / "truth" / "lost_sales.csv"
    if lost_p.exists():
        menu = store.df("SELECT item, chashu_portions FROM menu").set_index("item").chashu_portions
        lost = pd.read_csv(lost_p)
        lost = lost[lost.business_date == date]
        add = [{"t": r.time_h, "channel": r.channel, "need": sum(menu.get(x, 0) for x in r.items.split("|"))} for r in lost.itertuples()]
        ev = pd.concat([ev[["t", "channel", "need"]], pd.DataFrame(add, columns=["t", "channel", "need"])]).sort_values("t")
    true_left = par * (1 + rng.normal(0, count_error))
    seen_left = par
    counted, paused_at, cancels, held, recounts = False, None, 0, 0.0, 0
    rate = 0.0
    last_t = None
    for r in ev.itertuples():
        if r.need <= 0:
            continue
        app = r.channel != "in_store"
        if recount and not counted and seen_left < recount_at:  # Gondola only knows what it believes
            seen_left = true_left + int(rng.integers(-2, 3)); counted = True; recounts += 1
        if last_t is not None and r.t > last_t:
            rate = 0.8 * rate + 0.2 * (r.need / max((r.t - last_t) * 60, 0.5))
        last_t = r.t
        if paused_at is None and seen_left < buffer_portions + rate * delay_min:
            paused_at = r.t
        if app and paused_at is not None and r.t >= paused_at + delay_min / 60:
            held += r.need; continue
        if true_left >= r.need:
            true_left -= r.need; seen_left -= r.need
        elif app:
            cancels += 1
    return {"date": date, "cancels": cancels, "held_back": round(held, 1), "recounts": recounts,
            "paused_at": None if paused_at is None else f"{int(paused_at):02d}:{int(paused_at % 1 * 60):02d}"}
