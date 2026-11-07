"""Test the pivot ideas on the demo year.

1. Channel allocation for a scarce prepped item (chashu): status quo vs Guard vs Guard + forecast prep vs
   allocation (keep enough for expected dine-in demand, pause apps earlier when it's scarce).
   Uses true (uncensored) demand: served orders + cancelled orders + lost sales from data/truth.
2. Kitchen capacity: how often forecast/actual orders exceed what the scheduled line can cook, and what a
   throttle (longer app prep times / short app pauses at forecast overload) would do under stated assumptions.

    python scripts/pivot_sim.py      -> out/pivot_sim.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gondola.metrics import Store  # noqa: E402
from gondola.tools import demand, plan  # noqa: E402

COMMISSION = {"doordash": 0.25, "ubereats": 0.27, "grubhub": 0.20, "in_store": 0.029}
FOOD_COST = 0.30          # share of base menu price
BUFFER = 8                # portions
CANCEL_COST = 6.0         # $ equivalent of a store-caused cancellation (score risk + refund handling), assumption


def demand_events(st: Store) -> pd.DataFrame:
    menu = st.df("SELECT item, price, chashu_portions FROM menu").set_index("item")
    o = st.df("""SELECT o.business_date, o.created_at, o.channel, o.status, o.cancel_reason, l.item, l.price
                 FROM orders o JOIN order_lines l USING(order_id)""")
    o = o[o.item.map(menu.chashu_portions) > 0]
    o = o[(o.status == "completed") | (o.cancel_reason == "item_unavailable")]
    o["t"] = o.created_at.dt.hour + o.created_at.dt.minute / 60 + o.created_at.dt.second / 3600
    o["need"] = o.item.map(menu.chashu_portions)
    o["base"] = o.item.map(menu.price)
    ev = o[["business_date", "t", "channel", "need", "price", "base"]]
    lost = pd.read_csv(ROOT / "data/truth/lost_sales.csv", parse_dates=["business_date"])
    rows = []
    for r in lost.itertuples():
        for it in r.items.split("|"):
            if menu.chashu_portions.get(it, 0) > 0:
                p = menu.price[it] * (1.10 if r.channel != "in_store" else 1.0)
                rows.append((r.business_date, r.time_h, r.channel, menu.chashu_portions[it], p, menu.price[it]))
    ev = pd.concat([ev, pd.DataFrame(rows, columns=ev.columns)], ignore_index=True)
    ev["margin"] = ev.price * (1 - ev.channel.map(COMMISSION)) - ev.base * FOOD_COST
    return ev.sort_values(["business_date", "t"]).reset_index(drop=True)


def simulate(day: pd.DataFrame, par: float, policy: str, lag_min: float, dinein_profile: np.ndarray | None,
             total_profile: np.ndarray | None, expected_total: float | None, expected_dinein: float | None) -> dict:
    left, sold_out_t, paused_t = float(par), None, None
    out = {"margin": 0.0, "served": 0.0, "cancels": 0, "lost_in": 0.0, "lost_app": 0.0, "leftover": 0.0}
    for r in day.itertuples():
        app = r.channel != "in_store"
        if policy in ("guard", "allocate") and app and paused_t is None:
            if left < BUFFER:
                paused_t = r.t
            elif policy == "allocate" and dinein_profile is not None:
                b = int(min(max(r.t * 4, 0), 95))
                rem_in = expected_dinein * dinein_profile[b:].sum()
                rem_all = expected_total * total_profile[b:].sum()
                if rem_all > left and left < rem_in + BUFFER:  # scarce: keep the rest for dine-in
                    paused_t = r.t
        if app and paused_t is not None:
            out["lost_app"] += r.need
            continue
        if left >= r.need:
            left -= r.need
            out["margin"] += r.margin
            out["served"] += r.need
            continue
        if sold_out_t is None:
            sold_out_t = r.t
        if app and policy == "status_quo" and r.t <= sold_out_t + lag_min / 60:
            out["cancels"] += 1
        elif app:
            out["lost_app"] += r.need
        else:
            out["lost_in"] += r.need
    out["leftover"] = left
    out["leftover_cost"] = left * plan.CHASHU_COST * 0.4
    out["net"] = out["margin"] - out["leftover_cost"] - out["cancels"] * CANCEL_COST
    return out


def allocation_study(st: Store) -> dict:
    ev = demand_events(st)
    prep = st.df("SELECT business_date, par FROM prep_log").set_index("business_date").par
    so = pd.read_csv(ROOT / "data/truth/sold_out_events.csv", parse_dates=["business_date"]).set_index("business_date").apps_live_minutes
    bt_path = ROOT / "out" / "backtest_120d.csv"
    bt = pd.read_csv(bt_path) if bt_path.exists() else demand.rolling_backtest(st, days=120)
    bt["date"] = pd.to_datetime(bt.date)
    days = bt.date.iloc[30:]
    rows = []
    for d in days:
        day = ev[ev.business_date == d]
        if day.empty:
            continue
        hist = ev[(ev.business_date < d) & (ev.business_date >= d - pd.Timedelta(days=28))]
        same = hist[hist.business_date.dt.dayofweek == d.dayofweek]
        n_days = max(same.business_date.nunique(), 1)
        bins = np.zeros(96); bins_in = np.zeros(96)
        for r in same.itertuples():
            b = int(min(r.t * 4, 95)); bins[b] += r.need
            if r.channel == "in_store":
                bins_in[b] += r.need
        prof, prof_in = bins / max(bins.sum(), 1), bins_in / max(bins_in.sum(), 1)
        i = bt.index[bt.date == d][0]
        h = bt.iloc[max(0, i - 60):i]
        lo, hi = np.quantile(h.actual / h.predicted, [0.1, 0.9])
        p50 = float(bt.loc[i, "predicted"])
        ppo = float(same.need.sum() / max(same.groupby("business_date").size().mean(), 1) / n_days) if False else None
        # portions per order from trailing same weekdays (uncensored demand / orders forecast scale)
        dem_hist = same.groupby("business_date").need.sum()
        orders_hist = st.df("SELECT business_date, COUNT(*) n FROM orders WHERE business_date IN (SELECT unnest(?::DATE[])) GROUP BY 1",
                            [[x.date() for x in dem_hist.index]]).set_index("business_date").n
        ppo = float((dem_hist / orders_hist.reindex(dem_hist.index).values).mean())
        nv = plan.newsvendor_par(p50 * lo, p50, p50 * hi, ppo)["chashu_portions"]
        exp_total = p50 * ppo
        exp_in = exp_total * (bins_in.sum() / max(bins.sum(), 1))
        lag = float(so.get(d, np.clip(np.random.default_rng(d.dayofyear).gamma(2.2, 14), 8, 75)))
        habit = float(prep.get(d, nv))
        for name, par, pol in (("status quo", habit, "status_quo"), ("guard", habit, "guard"),
                               ("forecast prep + guard", nv, "guard"), ("forecast prep + allocation", nv, "allocate"),
                               ("habit prep + allocation", habit, "allocate")):
            r = simulate(day, par, pol, lag, prof_in, prof, exp_total, exp_in)
            rows.append({"date": d, "policy": name, "par": par, **r})
    df = pd.DataFrame(rows)
    s = df.groupby("policy").agg(days=("date", "nunique"), avg_par=("par", "mean"), cancels=("cancels", "sum"),
                                 portions_turned_away_dinein=("lost_in", "sum"), portions_not_offered_apps=("lost_app", "sum"),
                                 leftover_portions=("leftover", "sum"), chashu_margin=("margin", "sum"), net=("net", "sum")).round(1)
    base = s.loc["status quo", "net"]
    s["net_vs_status_quo"] = (s.net - base).round(0)
    return {"days": int(df.date.nunique()), "table": s.reset_index().to_dict("records")}


def capacity_study(st: Store) -> dict:
    """Kitchen load vs line capacity (2 cooks before 5 pm, 3 after; 7.5 orders per cook per 15 min).

    The demo data has no kitchen-capacity effect on demand, so this measures quote accuracy, not lost sales:
    baseline quotes a fixed 15-minute prep time on the apps; the throttle quotes 15 min + the wait FORECAST from
    the last 4 same weekdays (no hindsight). An app order is late if its real wait exceeds its quote by > 5 min.
    """
    o = st.df("""SELECT business_date, time_bucket(INTERVAL 15 MINUTE, created_at) b, channel, COUNT(*) n FROM orders
                 WHERE status='completed' GROUP BY 1,2,3""")
    o["slot"] = o.b.dt.hour * 4 + o.b.dt.minute // 15
    cap = lambda slot: (2 if slot < 68 else 3) * 7.5
    tot = o.pivot_table(index="business_date", columns="slot", values="n", aggfunc="sum", fill_value=0)
    app = o[o.channel != "in_store"].pivot_table(index="business_date", columns="slot", values="n", aggfunc="sum", fill_value=0)
    app = app.reindex(columns=tot.columns, fill_value=0)

    def waits(row):
        backlog, w = 0.0, []
        for slot, n in row.items():
            q = backlog + n
            c = cap(slot)
            backlog = max(q - c, 0)
            w.append(15 * backlog / c)  # minutes of work waiting when an order in this slot arrives
        return np.array(w)

    days = [d for d in tot.index if d >= pd.Timestamp("2026-08-08")]
    late_b = late_t = n_app = 0.0
    over_slots = 0
    for d in days:
        actual_w = waits(tot.loc[d])
        prev = [x for x in tot.index if x < d and x.dayofweek == d.dayofweek][-4:]
        fc_w = np.mean([waits(tot.loc[x]) for x in prev], axis=0) if prev else np.zeros(len(actual_w))
        a = app.loc[d].values
        n_app += a.sum()
        late_b += a[actual_w > 5].sum()                       # quoted 15 min, real 15 + wait
        late_t += a[actual_w > fc_w + 5].sum()                # quoted 15 + forecast wait
        over_slots += int((actual_w > 5).sum())
    nd = len(days)
    return {"days": nd, "app_orders_per_day": round(n_app / nd, 1), "slots_backed_up_per_day": round(over_slots / nd, 2),
            "late_app_orders_per_day_fixed_quote": round(late_b / nd, 1),
            "late_app_orders_per_day_forecast_quote": round(late_t / nd, 1),
            "assumption": "capacity 7.5 orders/cook/15 min, 2 cooks before 5 pm and 3 after; demand not affected by waits"}


if __name__ == "__main__":
    st = Store()
    res = {"allocation": allocation_study(st), "capacity": capacity_study(st)}
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "pivot_sim.json").write_text(json.dumps(res, indent=1, default=str))
    print(pd.DataFrame(res["allocation"]["table"]).to_string())
    print(json.dumps(res["capacity"], indent=1))


def guard_sensitivity(st: Store) -> list[dict]:
    """Guard under real-world error: the portion count is off by sigma (yield/count error) and the pause reaches
    the apps `delay` minutes late. Habit prep, so results isolate Guard."""
    ev = demand_events(st)
    prep = st.df("SELECT business_date, par FROM prep_log").set_index("business_date").par
    days = sorted(ev.business_date.unique())[-90:]
    rows = []
    for sigma in (0.0, 0.05, 0.10):
        for delay in (0, 5, 15):
            for buf in (8, 15, 25):
                rng = np.random.default_rng(42)
                canc = held = 0.0
                base_canc = 0
                for d in days:
                    day = ev[ev.business_date == d]
                    par = float(prep.get(d, 0))
                    true_par = par * (1 + rng.normal(0, sigma))  # what was really made vs what Gondola thinks
                    left_true, left_seen, pause_t, live_until = true_par, par, None, None
                    for r in day.itertuples():
                        app = r.channel != "in_store"
                        if pause_t is None and left_seen < buf:
                            pause_t = r.t
                        if app and pause_t is not None and r.t >= pause_t + delay / 60:
                            held += r.need
                            continue
                        if left_true >= r.need:
                            left_true -= r.need; left_seen -= r.need
                        elif app:
                            canc += 1
                rows.append({"count_error_sd": sigma, "pause_delay_min": delay, "buffer_portions": buf,
                             "cancels_90d": int(canc), "portions_held_back": round(held, 0)})
    return rows


if __name__ == "__main__" and "--sens" in sys.argv:
    r = guard_sensitivity(Store())
    p = ROOT / "out" / "pivot_sim.json"
    j = json.loads(p.read_text()); j["guard_sensitivity"] = r; p.write_text(json.dumps(j, indent=1, default=str))
    print(pd.DataFrame(r).pivot_table(index=["count_error_sd", "pause_delay_min"], columns="buffer_portions", values="cancels_90d"))


def guard_with_recount(st: Store) -> list[dict]:
    """Same errors, but when Gondola thinks ~40 portions are left it asks the line for a quick count
    (one text/tablet tap); the count is off by at most +/-2 portions."""
    ev = demand_events(st)
    prep = st.df("SELECT business_date, par FROM prep_log").set_index("business_date").par
    days = sorted(ev.business_date.unique())[-90:]
    rows = []
    for sigma in (0.05, 0.10):
        for delay in (5, 15):
            for buf in (8, 15):
                rng = np.random.default_rng(42)
                canc = held = recounts = 0
                for d in days:
                    day = ev[ev.business_date == d]
                    par = float(prep.get(d, 0))
                    left_true = par * (1 + rng.normal(0, sigma)); left_seen = par
                    pause_t, counted = None, False
                    for r in day.itertuples():
                        app = r.channel != "in_store"
                        if not counted and left_seen < 120:  # trigger on the believed count only
                            left_seen = left_true + rng.integers(-2, 3); counted = True; recounts += 1
                        if pause_t is None and left_seen < buf + delay * 0.6:  # buffer covers expected sales during the delay
                            pause_t = r.t
                        if app and pause_t is not None and r.t >= pause_t + delay / 60:
                            held += r.need; continue
                        if left_true >= r.need:
                            left_true -= r.need; left_seen -= r.need
                        elif app:
                            canc += 1
                rows.append({"count_error_sd": sigma, "pause_delay_min": delay, "buffer_portions": buf,
                             "cancels_90d": int(canc), "portions_held_back": int(held), "recount_prompts": int(recounts)})
    return rows


if __name__ == "__main__" and "--recount" in sys.argv:
    r = guard_with_recount(Store())
    p = ROOT / "out" / "pivot_sim.json"
    j = json.loads(p.read_text()); j["guard_with_recount"] = r; p.write_text(json.dumps(j, indent=1, default=str))
    print(pd.DataFrame(r).to_string())
