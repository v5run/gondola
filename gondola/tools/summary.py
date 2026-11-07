"""Monthly summary, written before that month's daily PDFs expire. Built from the metrics layer and the
stored findings, never by re-reading PDFs, so numbers match the dailies exactly.

monthly_summary() -> the JSON kept in the bucket (730 days); monthly_report_context() -> what the monthly report
template (report/templates/monthly.html) renders from it."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .. import NP
from ..metrics import Store

CHANNELS = ["in_store", "doordash", "ubereats", "grubhub"]
CHANNEL_NAME = {"in_store": "In-store", "doordash": "DoorDash", "ubereats": "Uber Eats", "grubhub": "Grubhub"}


def _events(x) -> list[str]:
    return [e for e in str(x).split("; ") if e and e not in ("None", "nan")]


def _totals(store: Store, d: pd.DataFrame, s: pd.Timestamp, e: pd.Timestamp) -> dict:
    m = d[(d.business_date >= s) & (d.business_date <= e)]
    o = m[m.orders > 0]
    ns, n = float(o.net_sales.sum()), int(o.orders.sum())
    ch = store.df("SELECT channel, SUM(subtotal) s FROM orders WHERE status='completed' AND business_date BETWEEN ? AND ? "
                  "GROUP BY 1", [s.date(), e.date()]).set_index("channel").s
    return {"days_open": int(len(o)), "net_sales": round(ns, 2), "orders": n, "avg_ticket": round(ns / n, 2) if n else None,
            "labour_pct": round(float(o.labour_cost.sum() / ns), 4) if ns else None, "cancels": int(o.cancels.sum()),
            "avoidable_cancels": int(o.avoidable_cancels.sum()),
            "net_sales_per_day": round(ns / len(o), 2) if len(o) else None,
            "by_channel": {c: round(float(ch.get(c, 0.0)), 2) for c in CHANNELS}}


def _pct(a, b):
    return round(float(a / b - 1), 4) if a is not None and b else None


def monthly_summary(store: Store, month: str, closes_state: dict | None = None, out_dir: Path | None = None) -> dict:
    """month: 'YYYY-MM'. closes_state: out/closes.json (findings per night). out_dir: the app's out/ folder, for the
    nightly close files (alerts sent), stored forecasts and the outbox."""
    s = pd.Timestamp(month + "-01")
    e = s + pd.offsets.MonthEnd(0)
    ps = s - pd.DateOffset(months=1)
    d = store.daily_frame()
    m = d[(d.business_date >= s) & (d.business_date <= e)]
    mo = m[m.orders > 0]
    cur = _totals(store, d, s, e)
    has_prev = len(d[(d.business_date >= ps) & (d.business_date < s) & (d.orders > 0)]) > 0
    prev = _totals(store, d, ps, s - pd.Timedelta(days=1)) if has_prev else None
    best = mo.nlargest(1, "net_sales").iloc[0]
    worst = mo.nsmallest(1, "net_sales").iloc[0]

    # usual for the same weekday (the month's own average per weekday), to say how unusual best/worst were
    dow_avg = mo.groupby(mo.business_date.dt.dayofweek).net_sales.mean()

    def day(r):
        usual = float(dow_avg.get(r.business_date.dayofweek, 0) or 0)
        return {"date": str(r.business_date.date()), "net_sales": round(float(r.net_sales), 2), "orders": int(r.orders),
                "events": "; ".join(_events(r.events)) or None, "rain": bool(r.rain) if r.rain == r.rain else False,
                "dow": r.business_date.day_name(), "vs_weekday_avg_pct": _pct(float(r.net_sales), usual)}

    prep = store.df("SELECT business_date, par, used, sold_out FROM prep_log WHERE business_date BETWEEN ? AND ? ORDER BY 1",
                    [s.date(), e.date()])
    so_dates = [str(pd.Timestamp(x).date()) for x in prep[prep.sold_out].business_date]
    canc = store.df("SELECT business_date, COUNT(*) n FROM orders WHERE cancel_reason='item_unavailable' AND channel <> 'in_store' "
                    "AND business_date BETWEEN ? AND ? GROUP BY 1", [s.date(), e.date()])
    so_cancels = int(canc.n.sum()) if len(canc) else 0
    # what Guard does on those nights (replayed: pause the apps before the item runs out, keep it for dine-in)
    from . import guard
    guarded = [guard.guarded_day(store, x, count_error=0.05, delay_min=2.0, seed=i) for i, x in enumerate(so_dates)]
    with_guard = int(sum(g.get("cancels", 0) for g in guarded))

    out = {"month": month, "month_name": s.strftime("%B %Y"), "start": str(s.date()), "end": str(e.date()), **cur,
           "vs_prev_month_pct": _pct(cur["net_sales_per_day"], prev["net_sales_per_day"]) if prev else None,
           "prev": ({"month": ps.strftime("%Y-%m"), "month_name": ps.strftime("%B %Y"), **prev} if prev else None),
           "vs_prev": ({"net_sales": _pct(cur["net_sales"], prev["net_sales"]), "orders": _pct(cur["orders"], prev["orders"]),
                        "avg_ticket": _pct(cur["avg_ticket"], prev["avg_ticket"]),
                        "net_sales_per_day": _pct(cur["net_sales_per_day"], prev["net_sales_per_day"]),
                        "labour_pct_pts": round((cur["labour_pct"] or 0) - (prev["labour_pct"] or 0), 4),
                        "avoidable_cancels": cur["avoidable_cancels"] - prev["avoidable_cancels"]} if prev else None),
           "best_day": day(best), "worst_day": day(worst),
           "daily": _daily_rows(m, s, e),
           "sold_out_days": len(so_dates), "sold_out_dates": so_dates, "sold_out_app_cancels": so_cancels,
           "sold_out_app_cancels_with_guard": with_guard, "cancels_avoided": max(so_cancels - with_guard, 0)}

    # forecast accuracy: the forecast each close stored for the next day, else the backtest of that day
    fc_rows = []
    fdir = Path(out_dir) / "forecasts" if out_dir else None
    bt = pd.read_csv(Path(out_dir) / "backtest_cache.csv") if out_dir and (Path(out_dir) / "backtest_cache.csv").exists() else None
    for r in mo.itertuples():
        ds = str(r.business_date.date())
        f = fdir / f"{ds}.json" if fdir else None
        if f is not None and f.exists():
            j = json.loads(f.read_text(encoding="utf-8"))
            fc_rows.append({"date": ds, "p50": j["p50"], "p10": j.get("p10"), "p90": j.get("p90"), "actual": int(r.orders),
                            "source": "stored"})
        elif bt is not None and ds in set(bt.date.astype(str)):
            b = bt[bt.date.astype(str) == ds].iloc[0]
            fc_rows.append({"date": ds, "p50": float(b.predicted), "p10": None, "p90": None, "actual": int(r.orders),
                            "naive": float(b.naive_same_weekday), "source": "backtest"})
    fc = None
    if fc_rows:
        f_ = pd.DataFrame(fc_rows)
        err = (f_.p50 - f_.actual).abs() / f_.actual
        rng = f_.dropna(subset=["p10", "p90"])
        within = ((rng.actual >= rng.p10) & (rng.actual <= rng.p90)).mean() if len(rng) else None
        naive = None
        if bt is not None:
            bm = bt[bt.date.astype(str).isin(f_.date)]
            naive = round(float(bm.naive_error_pct.abs().mean()), 4) if len(bm) else None
        fc = {"days_scored": int(len(f_)), "stored": int((f_.source == "stored").sum()), "mape": round(float(err.mean()), 4),
              "within_range_pct": round(float(within), 4) if within is not None else None, "naive_mape": naive,
              "worst_miss": {"date": f_.loc[err.idxmax(), "date"], "error_pct": round(float((f_.p50 - f_.actual).loc[err.idxmax()]
                                                                                       / f_.actual.loc[err.idxmax()]), 4)}}
    out["forecast"] = fc

    if closes_state:
        nights = {k: v for k, v in closes_state.items() if not k.startswith("_") and k[:7] == month}
        fs = [f for v in nights.values() for f in v.get("findings", [])]
        out["urgent_alerts"] = sum(1 for f in fs if f.get("urgency") == "urgent")
        out["recoverable_flagged_usd"] = round(sum(f.get("recoverable_usd") or 0 for f in fs if f["kind"] == "payout_short"), 2)
        out["closes"] = {"nights": len(nights), "done": sum(1 for v in nights.values() if v.get("status") == "done"),
                         "partial": sum(1 for v in nights.values() if v.get("status") == "partial"),
                         "first": min(nights) if nights else None, "last": max(nights) if nights else None}
        out["money"] = {"recoverable_flagged_usd": out["recoverable_flagged_usd"],
                        "payout_reports_short": sum(1 for f in fs if f["kind"] == "payout_short"),
                        "disputable_charges": int(sum(f.get("n_disputable") or 0 for f in fs if f["kind"] == "payout_short")),
                        "payout_short_usd": round(sum(f.get("impact_usd") or 0 for f in fs if f["kind"] == "payout_short"), 2),
                        "cash_short_usd": round(sum(f.get("impact_usd") or 0 for f in fs if f["kind"] == "cash_short"), 2),
                        "cash_short_nights": sum(1 for f in fs if f["kind"] == "cash_short")}
        top = sorted((f for f in fs if f["kind"] == "payout_short"), key=lambda f: -(f.get("recoverable_usd") or 0))[:4]
        out["money"]["top"] = [{"title": f.get("title"), "recoverable_usd": f.get("recoverable_usd"), "channel": f.get("channel_name")}
                               for f in top]
        # what was sent: the close files hold each night's alerts
        sms = emails = 0
        if out_dir:
            for ds in nights:
                p = Path(out_dir) / f"close_{ds}.json"
                if not p.exists():
                    continue
                try:
                    al = json.loads(p.read_text(encoding="utf-8")).get("alerts") or []
                except ValueError:
                    continue
                sms += sum(1 for a in al if a.get("channel", "sms") == "sms" and _sent(a))
            ob = Path(out_dir) / "outbox.jsonl"
            if ob.exists():
                for line in ob.read_text(encoding="utf-8").splitlines():
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("channel") == "email" and str(r.get("ts", ""))[:7] == month and _sent(r):
                        emails += 1
        out["alerts"] = {"texts": sms, "emails": emails, "urgent_items": out["urgent_alerts"],
                         "quiet_nights": len(nights) - sum(1 for v in nights.values()
                                                           if any(f.get("urgency") == "urgent" for f in v.get("findings", [])))}
    return out


def _daily_rows(m: pd.DataFrame, s: pd.Timestamp, e: pd.Timestamp) -> list[dict]:
    """Every calendar day of the month; days without orders (closed) are zero and marked closed."""
    by = m.set_index("business_date")
    rows = []
    for t in pd.date_range(s, e):
        if t in by.index and float(by.loc[t, "orders"]) > 0:
            rows.append({"date": str(t.date()), "net_sales": round(float(by.loc[t, "net_sales"]), 2), "orders": int(by.loc[t, "orders"]),
                         "closed": False})
        else:
            rows.append({"date": str(t.date()), "net_sales": 0.0, "orders": 0, "closed": True})
    return rows


def _sent(a: dict) -> bool:
    st = a.get("status") or ""
    if st == "duplicate_suppressed":
        st = a.get("original_status") or ""
    return st in ("sent", "dry_run")


def _money(x) -> str:
    return f"${x:,.0f}" if x is not None else "n/a"


def _delta(p, unit: str = "") -> str:
    return f"{p:+.0%}{unit}" if p is not None else "no earlier month"


def monthly_headline(sm: dict) -> str:
    per_day = sm.get("vs_prev_month_pct")
    tone = ("A strong month" if per_day is not None and per_day > 0.03 else
            "A softer month" if per_day is not None and per_day < -0.03 else "A steady month")
    return f"{tone}: {_money(sm.get('net_sales'))} in {pd.Timestamp(sm['month'] + '-01'):%B}"


def monthly_report_context(sm: dict, store_name: str, generated: str, rebuilt: str | None = None) -> dict:
    """Template context for report/templates/monthly.html from a monthly_summary()."""
    from ..report.render import bars_svg
    s = pd.Timestamp(sm["start"])
    prev_name = (sm.get("prev") or {}).get("month_name", "").split(" ")[0] or "the month before"
    vp = sm.get("vs_prev") or {}
    per_day = sm.get("vs_prev_month_pct")
    headline = monthly_headline(sm)
    summary = (f"{sm['orders']:,} orders over {sm['days_open']} open days, {_money(sm['net_sales_per_day'])} a day"
               + (f" ({_delta(per_day)} a day on {prev_name})." if per_day is not None else ".")
               + (f" Chashu sold out on {sm['sold_out_days']} night{'s' if sm['sold_out_days'] != 1 else ''}." if sm["sold_out_days"] else
                  " Chashu never sold out."))
    neg = lambda x: x is not None and x < 0
    kpis = [{"label": "Net sales", "value": _money(sm["net_sales"]), "delta": f"{_delta(vp.get('net_sales'))} vs {prev_name}", "bad": neg(vp.get("net_sales"))},
            {"label": "Orders", "value": f"{sm['orders']:,}", "delta": f"{_delta(vp.get('orders'))} vs {prev_name}", "bad": neg(vp.get("orders"))},
            {"label": "Average ticket", "value": f"${sm['avg_ticket']:.2f}" if sm["avg_ticket"] else "n/a",
             "delta": f"{_delta(vp.get('avg_ticket'))} vs {prev_name}", "bad": neg(vp.get("avg_ticket"))},
            {"label": "Labour", "value": f"{sm['labour_pct']:.1%}" if sm["labour_pct"] is not None else "n/a",
             "delta": (f"{vp['labour_pct_pts'] * 100:+.1f} pts vs {prev_name}" if vp.get("labour_pct_pts") is not None else "of net sales"),
             "bad": (sm["labour_pct"] or 0) > 0.30}]
    daily = sm["daily"]
    idx = {r["date"]: i for i, r in enumerate(daily)}
    marks = {i: "closed" for i, r in enumerate(daily) if r["closed"]}
    for x in sm.get("sold_out_dates", []):
        if x in idx:
            marks[idx[x]] = "soldout"
    marks[idx[sm["best_day"]["date"]]] = "best"
    marks[idx[sm["worst_day"]["date"]]] = "worst"
    chart = bars_svg([r["net_sales"] for r in daily], [str(pd.Timestamp(r["date"]).day) for r in daily], marks)

    def ctx_day(x):
        t = pd.Timestamp(x["date"])
        why = [w for w in [x.get("events"), "rain" if x.get("rain") else None] if w]
        vs = x.get("vs_weekday_avg_pct")
        return {"label": t.strftime(f"%a %b %{NP}d"), "net_sales": _money(x["net_sales"]), "orders": x["orders"],
                "context": ", ".join(why) or "no weather or events of note",
                "vs": f"{vs:+.0%} vs the month's average {x['dow']}" if vs is not None else ""}

    ch = sm.get("by_channel") or {}
    prev_ch = (sm.get("prev") or {}).get("by_channel") or {}
    channels = [{"name": CHANNEL_NAME[c], "value": _money(ch.get(c)), "share": (ch.get(c, 0) / sm["net_sales"]) if sm["net_sales"] else 0,
                 "delta": _delta(_pct(ch.get(c), prev_ch.get(c))) if prev_ch else ""} for c in CHANNELS]
    fc = sm.get("forecast")
    money = sm.get("money") or {}
    alerts = sm.get("alerts") or {}
    closes = sm.get("closes") or {}
    coverage = None
    if not closes.get("nights"):
        coverage = "Gondola wasn't closing this store yet this month; money and alert figures start with its first close."
    elif closes.get("first") and closes["first"] > sm["start"]:
        coverage = f"Gondola closed {closes['nights']} nights this month (from {pd.Timestamp(closes['first']):%b %{NP}d}); money and alert figures cover those nights."
    return {"store_name": store_name, "month": sm["month"], "month_name": sm["month_name"], "headline": headline,
            "summary": summary, "kpis": kpis, "chart_svg": chart, "best": ctx_day(sm["best_day"]), "worst": ctx_day(sm["worst_day"]),
            "channels": channels, "prev_name": prev_name, "money": money, "alerts": alerts, "closes": closes, "coverage": coverage,
            "sold_out": {"days": sm["sold_out_days"], "dates": ", ".join(pd.Timestamp(x).strftime(f"%b %{NP}d") for x in sm["sold_out_dates"]),
                         "app_cancels": sm["sold_out_app_cancels"], "with_guard": sm["sold_out_app_cancels_with_guard"],
                         "avoided": sm["cancels_avoided"]},
            "cancels": sm["cancels"], "avoidable_cancels": sm["avoidable_cancels"],
            "forecast": ({"days": fc["days_scored"], "mape": f"{fc['mape']:.1%}",
                          "within": f"{fc['within_range_pct']:.0%}" if fc.get("within_range_pct") is not None else None,
                          "naive": f"{fc['naive_mape']:.1%}" if fc.get("naive_mape") is not None else None,
                          "stored": fc["stored"],
                          "worst": f"{pd.Timestamp(fc['worst_miss']['date']):%a %b %{NP}d} ({fc['worst_miss']['error_pct']:+.0%})"} if fc else None),
            "generated": generated, "rebuilt": rebuilt}
