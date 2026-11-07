"""Stock Agent tools: what do we have left?

Ledger: on_hand = last_count + received - sold x recipe - waste.
On count days the ledger is compared with the count; persistent gaps become findings.
"""
from __future__ import annotations

import pandas as pd

from ..metrics import Store

CHASHU_PER_KG_BELLY = 7.0
VARIANCE_FLAG = 0.06    # 6% of usage since last count
MIN_UNITS = 3


def theoretical_usage(store: Store, start: str, end: str) -> pd.DataFrame:
    q = """
    SELECT o.business_date, r.sku, SUM(r.qty) AS used
    FROM orders o JOIN order_lines l USING(order_id) JOIN recipes r ON r.item = l.item
    WHERE o.status = 'completed' AND o.business_date BETWEEN ? AND ?
    GROUP BY 1, 2"""
    u = store.df(q, [start, end])
    # pork belly is used through chashu prep, not directly by menu items
    prep = store.df("SELECT business_date, par / ? AS used FROM prep_log WHERE business_date BETWEEN ? AND ?",
                    [CHASHU_PER_KG_BELLY, start, end])
    prep["sku"] = "pork_belly"
    return pd.concat([u, prep[["business_date", "sku", "used"]]], ignore_index=True)


def update_ledger(store: Store, date: str) -> dict:
    """Roll each tracked SKU forward from its last count to `date` and compare with a count taken on `date`."""
    counts = store.df("SELECT * FROM counts WHERE business_date <= ?", [date])
    if counts.empty:
        return {"date": date, "status": "no_counts"}
    out_rows, findings = [], []
    count_dates = sorted(counts.business_date.unique())
    today = pd.Timestamp(date)
    prev_dates = [d for d in count_dates if d < today]
    if not prev_dates:
        return {"date": date, "status": "first_count"}
    prev = prev_dates[-1]
    start = (pd.Timestamp(prev) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    use = theoretical_usage(store, start, date).groupby("sku").used.sum()
    recv = store.df("SELECT sku, SUM(qty) q FROM invoices WHERE business_date BETWEEN ? AND ? GROUP BY 1", [start, date]).set_index("sku").q
    waste = store.df("SELECT sku, SUM(qty) q FROM waste WHERE business_date BETWEEN ? AND ? GROUP BY 1", [start, date]).set_index("sku").q
    last = counts[counts.business_date == prev].set_index("sku").counted_qty
    now = counts[counts.business_date == today].set_index("sku").counted_qty
    for sku, last_q in last.items():
        led = last_q + recv.get(sku, 0) - use.get(sku, 0) - waste.get(sku, 0)
        row = {"sku": sku, "last_count": round(last_q, 2), "received": round(float(recv.get(sku, 0)), 2),
               "used": round(float(use.get(sku, 0)), 2), "waste": round(float(waste.get(sku, 0)), 2), "ledger": round(led, 2)}
        if sku in now.index:
            gap = now[sku] - led
            denom = max(use.get(sku, 0), 1e-9)
            row.update(counted=round(float(now[sku]), 2), gap=round(float(gap), 2), gap_pct=round(float(gap / denom), 4))
            if gap < 0 and abs(gap) / denom > VARIANCE_FLAG and abs(gap) >= MIN_UNITS:
                findings.append({"agent": "stock", "kind": "usage_variance", "sku": sku, "business_date": date,
                                 "title": f"{sku}: {abs(gap):.1f} more used than sales explain ({abs(gap)/denom:.0%})",
                                 "gap": round(float(gap), 2), "gap_pct": round(float(gap / denom), 4)})
        out_rows.append(row)
    return {"date": date, "since": str(pd.Timestamp(prev).date()), "rows": out_rows, "findings": findings}


def variance_history(store: Store, sku: str | None = None) -> pd.DataFrame:
    """Ledger vs count for every count day. Used to spot shrink and over-portioning patterns."""
    days = store.df("SELECT DISTINCT business_date FROM counts ORDER BY 1").business_date
    rows = []
    for d in days[1:]:
        r = update_ledger(store, str(pd.Timestamp(d).date()))
        for x in r.get("rows", []):
            if "gap" in x and (sku is None or x["sku"] == sku):
                rows.append({"business_date": pd.Timestamp(d), **x})
    return pd.DataFrame(rows)


def chashu_today(store: Store, date: str) -> dict:
    r = store.df("SELECT * FROM prep_log WHERE business_date = ?", [date])
    return r.iloc[0].to_dict() if len(r) else {}
