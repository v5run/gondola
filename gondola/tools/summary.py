"""Monthly summary, written before that month's daily PDFs expire. Built from the metrics layer and the
stored findings, never by re-reading PDFs, so numbers match the dailies exactly."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..metrics import Store


def monthly_summary(store: Store, month: str, closes_state: dict | None = None) -> dict:
    s = pd.Timestamp(month + "-01")
    e = s + pd.offsets.MonthEnd(0)
    d = store.daily_frame()
    m = d[(d.business_date >= s) & (d.business_date <= e) & (d.orders > 0)]
    prev = d[(d.business_date >= s - pd.DateOffset(months=1)) & (d.business_date < s) & (d.orders > 0)]
    best = m.nlargest(1, "net_sales").iloc[0]
    worst = m.nsmallest(1, "net_sales").iloc[0]
    out = {"month": month, "days_open": int(len(m)), "net_sales": round(float(m.net_sales.sum()), 2),
           "orders": int(m.orders.sum()), "avg_ticket": round(float(m.net_sales.sum() / m.orders.sum()), 2),
           "vs_prev_month_pct": round(float(m.net_sales.mean() / prev.net_sales.mean() - 1), 4) if len(prev) else None,
           "best_day": {"date": str(best.business_date.date()), "net_sales": round(float(best.net_sales), 2), "events": best.events},
           "worst_day": {"date": str(worst.business_date.date()), "net_sales": round(float(worst.net_sales), 2), "events": worst.events},
           "avoidable_cancels": int(m.avoidable_cancels.sum()), "labour_pct": round(float(m.labour_cost.sum() / m.net_sales.sum()), 4)}
    so = store.df("SELECT COUNT(*) n FROM prep_log WHERE sold_out AND business_date BETWEEN ? AND ?", [s.date(), e.date()])
    out["sold_out_days"] = int(so.n[0])
    if closes_state:
        fs = [f for k, v in closes_state.items() if not k.startswith("_") and k[:7] == month for f in v.get("findings", [])]
        out["urgent_alerts"] = sum(1 for f in fs if f.get("urgency") == "urgent")
        out["recoverable_flagged_usd"] = round(sum(f.get("recoverable_usd") or 0 for f in fs if f["kind"] == "payout_short"), 2)
    return out
