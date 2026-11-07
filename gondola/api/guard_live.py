"""Guard, live: replay one service night order by order and stream what Guard sees and does.

Same logic as gondola.tools.guard.guarded_day:
- Gondola believes `par` portions were made; the kitchen really has par x (1 + count_error).
- When it believes plan.RECOUNT_AT portions are left it asks for one recount. The manager answers through
  POST /api/guard/{run_id}/recount; with no answer in 20 simulated minutes the true count +/-2 is used.
- Each app is paused when believed portions fall below the buffer plus what sells during that app's pause
  delay (plan.PAUSE_DELAY_MIN); the pause takes effect after that delay.
- Demand is the night's true chashu demand: served + cancelled orders + sales lost after sell-out (data/truth).
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..metrics import ROOT, Store
from ..tools import plan
from .runs import Run

APPS = ["doordash", "ubereats", "grubhub"]
CHANNELS = ["in_store"] + APPS
BUFFER = 8.0
APP_SHARE = 0.66


def _hm(t: float) -> str:
    m = int(round(t * 60))
    return f"{m // 60:02d}:{m % 60:02d}"


def demand_events(store: Store, date: str) -> pd.DataFrame:
    q = """SELECT o.created_at, o.channel, SUM(m.chashu_portions) need FROM orders o JOIN order_lines l USING(order_id)
           JOIN menu m ON m.item = l.item WHERE o.business_date = ? AND m.chashu_portions > 0
           AND (o.status='completed' OR o.cancel_reason='item_unavailable') GROUP BY ALL ORDER BY 1"""
    ev = store.df(q, [date])
    ev["t"] = ev.created_at.dt.hour + ev.created_at.dt.minute / 60 + ev.created_at.dt.second / 3600
    ev = ev[["t", "channel", "need"]]
    lost_p = ROOT / "data" / "truth" / "lost_sales.csv"
    if lost_p.exists():
        menu = store.df("SELECT item, chashu_portions FROM menu").set_index("item").chashu_portions
        lost = pd.read_csv(lost_p)
        lost = lost[lost.business_date == date]
        add = [{"t": r.time_h, "channel": r.channel, "need": sum(menu.get(x, 0) for x in r.items.split("|"))}
               for r in lost.itertuples()]
        if add:
            ev = pd.concat([ev, pd.DataFrame(add)], ignore_index=True)
    ev = ev[ev.need > 0].sort_values("t").reset_index(drop=True)
    return ev


def status_quo_cancels(store: Store, date: str) -> int:
    return int(store.df("SELECT COUNT(*) n FROM orders WHERE business_date = ? AND channel <> 'in_store' "
                        "AND cancel_reason = 'item_unavailable'", [date]).n[0])


def run_replay(run: Run, db: Path | str, date: str = "2026-11-05", speed: float = 60.0, count_error: float = 0.05,
               recount: bool = True, start_time: str = "17:00", par: float | None = None, seed: int = 7):
    try:
        store = Store(db)
        if par is None:
            pr = store.df("SELECT par FROM prep_log WHERE business_date = ?", [date])
            par = float(pr.par[0]) if len(pr) else 0.0
        ev = demand_events(store, date)
        close_h = 23.0 if pd.Timestamp(date).dayofweek in (4, 5) else 22.0
        sq = status_quo_cancels(store, date)
        rng = np.random.default_rng(seed)
        true_left = par * (1 + rng.normal(0, count_error))
        believed = float(par)
        sh, sm = (int(x) for x in start_time.split(":"))
        start_h = sh + sm / 60
        run.emit("start", {"date": date, "par": par, "start_time": start_time, "close": _hm(close_h), "speed": speed,
                           "count_error": count_error, "recount": recount})
        sold = {c: 0.0 for c in CHANNELS}
        available = {c: True for c in CHANNELS}
        decided = {a: None for a in APPS}      # time the pause was decided
        cancels, held = 0, 0.0
        rate, last_t = 0.0, None
        prompt_at, counted = None, False
        i = 0
        minute = 11 * 60  # store opens at 11:00; ticks are emitted from start_time
        end_min = int(close_h * 60)
        tick_sleep = 60.0 / max(speed, 1e-6)
        while minute <= end_min:
            t_now = minute / 60
            # 1) recount answer (or fallback after 20 simulated minutes)
            if recount and prompt_at is not None and not counted:
                if "recount" in run.inbox:
                    believed = float(run.inbox.pop("recount")); counted = True
                    run.emit("recount_done", {"t": _hm(t_now), "count": believed, "source": "manager"})
                elif t_now - prompt_at >= 20 / 60:
                    believed = true_left + int(rng.integers(-2, 3)); counted = True
                    run.emit("recount_done", {"t": _hm(t_now), "count": round(believed), "source": "line (no reply)"})
            # 2) orders up to this minute
            while i < len(ev) and ev.t.iloc[i] < t_now:
                r = ev.iloc[i]; i += 1
                ch, need, t = r.channel, float(r.need), float(r.t)
                if last_t is not None and t > last_t:
                    rate = 0.8 * rate + 0.2 * (need / max((t - last_t) * 60, 0.5))
                last_t = t
                if recount and prompt_at is None and believed < plan.RECOUNT_AT:
                    prompt_at = t
                    run.emit("recount_prompt", {"t": _hm(t), "believed_left": round(believed)})
                for a in APPS:
                    if decided[a] is None and believed < BUFFER + rate * APP_SHARE * plan.PAUSE_DELAY_MIN[a]:
                        decided[a] = t
                if ch in APPS:
                    live = decided[ch] is None or t < decided[ch] + plan.PAUSE_DELAY_MIN[ch] / 60
                    if not live:
                        held += need
                        continue
                    if true_left >= need:
                        true_left -= need; believed -= need; sold[ch] += need
                    else:
                        cancels += 1
                else:
                    if true_left >= need:
                        true_left -= need; believed -= need; sold[ch] += need
            # 3) availability flips
            for a in APPS:
                eff = decided[a] is not None and t_now >= decided[a] + plan.PAUSE_DELAY_MIN[a] / 60
                if eff and available[a]:
                    available[a] = False
                    run.emit("pause", {"app": a, "t": _hm(decided[a] + plan.PAUSE_DELAY_MIN[a] / 60)})
            if available["in_store"] and true_left < 0.5:
                available["in_store"] = False
                run.emit("sold_out", {"t": _hm(t_now), "where": "in_store"})
            if t_now >= start_h:
                run.emit("tick", {"t": _hm(t_now), "believed_left": round(max(believed, 0)),
                                  "sold": {k: round(v, 1) for k, v in sold.items()}, "available": dict(available),
                                  "cancels": cancels, "held_back": round(held, 1)})
                if tick_sleep > 0:
                    time.sleep(tick_sleep)
            minute += 1
        run.emit("done", {"status": "done", "cancels": cancels, "held_back": round(held, 1), "status_quo_cancels": sq,
                          "true_left": round(max(true_left, 0), 1)})
    except Exception as e:  # never leave a stream hanging
        run.emit("done", {"status": "failed", "error": "Replay failed", "cancels": None, "held_back": None, "status_quo_cancels": None})
