"""Books Agent tools: did we get paid right?

Expected payout is computed from the POS's own record of each app order and the store's contract rates.
It is compared line by line with what each platform reports. Nothing here files a dispute: the agent
drafts the evidence and the merchant submits it through the platform's own portal.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

from ..metrics import Store

CONTRACT = {"doordash": 0.25, "ubereats": 0.27, "grubhub": 0.20}
MARKETING_PER_PROMO_ORDER = 2.00
RATE_TOL = 0.004          # tolerance on effective commission rate
CASH_TOL = 5.00           # ordinary counting noise


@dataclass
class Finding:
    agent: str
    kind: str
    title: str
    impact_usd: float
    business_date: str
    channel: str | None = None
    evidence: list | None = None
    detail: dict | None = None

    def to_dict(self):
        return asdict(self)


def match_payouts(store: Store, date: str, channels: list[str] | None = None) -> dict:
    """Reconcile one business day. `channels`: only those whose payout report has arrived (default all)."""
    orders = store.df("SELECT * FROM orders WHERE business_date = ? AND channel <> 'in_store'", [date])
    lines = store.df("SELECT order_id, item, price FROM order_lines WHERE order_id IN "
                     "(SELECT order_id FROM orders WHERE business_date = ? AND channel <> 'in_store')", [date])
    pay = store.df("SELECT * FROM payout_lines WHERE business_date = ?", [date])
    findings: list[Finding] = []
    per_channel = []
    menu = store.df("SELECT item, price FROM menu")
    app_prices = {ch: set((menu.price * 1.10).round(2)) for ch in CONTRACT}
    items_by_order = lines.groupby("order_id").agg(items=("item", list), prices=("price", list)).to_dict("index")
    for ch, rate in CONTRACT.items():
        if channels is not None and ch not in channels:
            continue
        o = orders[(orders.channel == ch) & (orders.status == "completed")]
        p = pay[pay.channel == ch]
        exp = o.subtotal - (o.subtotal * rate).round(2) - o.promo.astype(float) * MARKETING_PER_PROMO_ORDER  # platforms round per order
        expected = float(exp.sum())
        reported = float(p.net_payout.sum())
        # 1. orders missing from the payout report
        missing = o[~o.order_id.isin(p.order_id)]
        for _, r in missing.iterrows():
            findings.append(Finding("books", "missing_from_payout", f"{ch} order {r.order_id} missing from payout",
                                    round(r.subtotal * (1 - rate) - MARKETING_PER_PROMO_ORDER * r.promo, 2), date, ch,
                                    [r.order_id]))
        m = p.merge(o[["order_id", "subtotal", "promo"]], on="order_id", how="inner", suffixes=("", "_pos"))
        m = m[m.status == "completed"]
        # 2. commission above contract
        if len(m):
            eff = m.commission.sum() / max(m.subtotal.sum(), 1e-9)
            if eff > rate + RATE_TOL:
                over = float((m.commission - m.subtotal * rate).clip(lower=0).sum())
                findings.append(Finding("books", "commission_overcharge",
                                        f"{ch} charged {eff:.1%} commission vs {rate:.0%} contract", round(over, 2), date, ch,
                                        m.order_id.tolist(), {"effective_rate": round(eff, 4), "contract_rate": rate}))
        # 3. error charges. Three outcomes, because order data alone can't settle every case:
        #    likely_valid (equals an item on the order), disputable (more than any item, or equals the price of a
        #    menu item that was NOT on the order), review (a partial amount: needs the manager's memory/photos).
        for _, r in m[m.error_charge > 0].iterrows():
            info = items_by_order.get(r.order_id, {"items": [], "prices": []})
            prices = [round(x, 2) for x in info["prices"]]
            ec = round(r.error_charge, 2)
            if r.get("adjustment", 0) and abs(r.adjustment - ec) < 0.01:
                continue  # the platform already reversed it
            if ec in prices:
                verdict, why = "likely_valid", "charge equals the price of an item on the order"
            elif ec > max(prices, default=0) + 0.01:
                verdict, why = "disputable", "charge is more than any single item on the order"
            elif ec in app_prices[ch]:
                verdict, why = "disputable", "charge equals the price of a menu item that wasn't on the order"
            else:
                verdict, why = "review", "partial charge: check the tablet photo or ticket"
            findings.append(Finding("books", f"error_charge_{verdict}", f"{ch} error charge ${ec:.2f} on {r.order_id}",
                                    ec if verdict == "disputable" else 0.0, date, ch, [r.order_id],
                                    {"items": info["items"], "prices": prices, "reason": why}))
        if reported - expected > 1:
            findings.append(Finding("books", "overpaid", f"{ch} paid ${reported - expected:.2f} more than expected", 0.0, date, ch,
                                    [], {"note": "check for duplicate or reversed lines before the platform claws it back"}))
        per_channel.append({"channel": ch, "orders": int(len(o)), "sales": round(float(o.subtotal.sum()), 2),
                            "expected": round(expected, 2), "reported": round(reported, 2),
                            "difference": round(reported - expected, 2),
                            "error_charges": round(float(p.error_charge.sum()), 2)})
    disputable = [f for f in findings if f.kind in ("error_charge_disputable", "missing_from_payout", "commission_overcharge")]
    return {"date": date, "channels": per_channel, "findings": [f.to_dict() for f in findings],
            "recoverable_usd": round(sum(f.impact_usd for f in disputable), 2)}


def cash_variance(store: Store, date: str) -> dict:
    """Sum every drawer shift of the day. A shift that isn't CLOSED (counted) is reported, never guessed."""
    s = store.df("SELECT * FROM cash_drawer_shifts WHERE business_date = ?", [date])
    if s.empty:
        return {"date": date, "status": "no_shift", "flag": False}
    open_ = s[(s.state != "CLOSED") | s.closed_cash.isna()]
    if len(open_):
        return {"date": date, "status": "drawer_not_closed", "flag": False, "open_shifts": open_.shift_id.tolist(),
                "expected": float(s.expected_cash.sum()), "counted": None, "difference": None}
    diff = round(float(s.closed_cash.sum() - s.expected_cash.sum()), 2)
    return {"date": date, "status": "closed", "shift_id": ",".join(s.shift_id), "state": "CLOSED", "shifts": int(len(s)),
            "expected": round(float(s.expected_cash.sum()), 2), "counted": round(float(s.closed_cash.sum()), 2),
            "difference": diff, "flag": abs(diff) > CASH_TOL}


def draft_dispute(finding: dict) -> str:
    """Evidence text for the merchant to paste into the platform's own dispute form."""
    d = finding.get("detail") or {}
    return (f"Order {finding['evidence'][0]} ({finding['business_date']}): error charge of ${finding['impact_usd']:.2f}. "
            f"Items on the order: {', '.join(d.get('items', []))} (prices {d.get('prices')}). "
            f"Reason we believe it is incorrect: {d.get('reason')}. Tablet shows the order was confirmed and handed off complete.")


def day_money(store: Store, date: str) -> dict:
    o = store.df("SELECT * FROM orders WHERE business_date = ? AND status='completed'", [date])
    lab = store.df("SELECT SUM(hours*wage) c, SUM(hours) h FROM labour WHERE business_date = ?", [date])
    net = float(o.subtotal.sum())
    card = o[(o.channel == "in_store") & (o.tender == "card")]
    card_fees = float((card.subtotal + card.tax + card.tip).sum() * 0.029 + 0.30 * len(card))
    commission = sum(float(o[o.channel == ch].subtotal.sum()) * r for ch, r in CONTRACT.items())
    labour = float(lab.c[0] or 0)
    return {"net_sales": round(net, 2), "orders": int(len(o)), "avg_ticket": round(net / max(len(o), 1), 2),
            "card_fees": round(card_fees, 2), "app_commission": round(commission, 2), "labour_cost": round(labour, 2),
            "labour_pct": round(labour / net, 4) if net else None, "labour_hours": float(lab.h[0] or 0)}
