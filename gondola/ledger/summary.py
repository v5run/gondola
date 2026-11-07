"""Running KPIs for the Past screen, computed only from the ledger (deterministic).

`summary(date, cutoff)` follows GET /api/past/summary in docs/architecture/TRI_WORKFLOW_API.md. Per order it prefers
Present's live events (wait/hold/late on `order.handed_off`) and falls back to the order-level events the ledger
builder writes from the POS. Waits, holds and promises are reported only from events that carry them; otherwise they
are None and `timing_source` says "none" (order-level data has no kitchen timing).
"""
from __future__ import annotations

from statistics import mean

from . import Event, Ledger, ledger

ORDER_TYPES = ["order.received", "order.handed_off", "order.cancelled", "order.refunded", "action.applied",
               "order.quoted", "order.deferred", "order.declined"]


def _richness(e: Event) -> int:
    p = e.payload
    return (0 if e.source == "pos" else 2) + (1 if p.get("wait_min") is not None else 0)


def per_order(events: list[Event]) -> dict[str, dict[str, Event]]:
    """{order_id: {type: best event}}: one event per order and type, preferring live (non-POS) events with timing."""
    out: dict[str, dict[str, Event]] = {}
    for e in events:
        oid = e.payload.get("order_id")
        if not oid:
            continue
        slot = out.setdefault(oid, {})
        cur = slot.get(e.type)
        if cur is None or _richness(e) > _richness(cur):
            slot[e.type] = e
    return out


def _cut_ts(date: str, cutoff: str | None) -> str | None:
    if not cutoff:
        return None
    hm = cutoff if len(cutoff) > 5 else cutoff + ":00"
    return f"{date}T{hm}" if len(hm) == 8 else f"{date}T{hm[:8]}"


def summary(date: str, cutoff: str | None = None, led: Ledger | None = None, *,
            events: list[Event] | None = None) -> dict:
    """KPIs for business `date` from events before `cutoff` ("HH:MM", None = the whole day)."""
    end = _cut_ts(date, cutoff)
    evs = (led or ledger()).query(date, ORDER_TYPES) if events is None else events
    if end:
        evs = [e for e in evs if e.ts < end]
    orders = per_order(evs)
    by_channel: dict[str, dict] = {}
    waits, holds, lates = [], [], []
    cancels: dict[str, int] = {}
    processed = refunds = 0
    sales = 0.0
    for oid, t in orders.items():
        rec = t.get("order.received")
        ch = (rec.payload.get("channel") if rec else None) or next((e.payload.get("channel") for e in t.values()
                                                                    if e.payload.get("channel")), "unknown")
        sub = float((rec.payload.get("subtotal") if rec else 0) or 0)
        if "order.refunded" in t:
            refunds += 1
        if "order.cancelled" in t:
            r = t["order.cancelled"].payload.get("reason") or "unknown"
            cancels[r] = cancels.get(r, 0) + 1
            continue
        h = t.get("order.handed_off")
        if h is None:
            continue
        processed += 1
        sales += sub
        c = by_channel.setdefault(ch, {"orders": 0, "sales": 0.0})
        c["orders"] += 1
        c["sales"] += sub
        p = h.payload
        if p.get("wait_min") is not None:
            waits.append(float(p["wait_min"]))
        if p.get("hold_min") is not None:
            holds.append(float(p["hold_min"]))
        if p.get("late_min") is not None:
            lates.append(float(p["late_min"]))
    for c in by_channel.values():
        c["sales"] = round(c["sales"], 2)
    received = sum(1 for t in orders.values() if "order.received" in t)
    in_progress = sum(1 for t in orders.values() if "order.received" in t and not ({"order.handed_off", "order.cancelled"} & set(t)))
    actions = sum(1 for e in evs if e.type == "action.applied")
    return {
        "date": date, "cutoff": cutoff, "processed": processed, "received": received, "in_progress": in_progress,
        "sales": round(sales, 2), "by_channel": dict(sorted(by_channel.items())),
        "promises_met": sum(1 for x in lates if x <= 0) if lates else None, "promises_total": len(lates),
        "promises_met_pct": round(sum(1 for x in lates if x <= 0) / len(lates), 4) if lates else None,
        "avg_wait_min": round(mean(waits), 1) if waits else None, "worst_wait_min": round(max(waits), 1) if waits else None,
        "avg_hold_min": round(mean(holds), 1) if holds else None,
        "late_orders": sum(1 for x in lates if x > 0), "worst_late_min": round(max(lates), 1) if lates else None,
        "cancels": sum(cancels.values()), "cancels_by_reason": dict(sorted(cancels.items())), "refunds": refunds,
        "actions_count": actions,
        "timing_source": "present" if waits or lates else "none",
        "order_source": "present" if any(e.source != "pos" for e in evs if e.type == "order.received") else "pos",
    }


def hourly(date: str, cutoff: str | None = None, led: Ledger | None = None) -> list[dict]:
    """Per clock hour: orders received, handed off, cancelled, actions (for the shift log)."""
    led = led or ledger()
    end = _cut_ts(date, cutoff)
    evs = [e for e in led.query(date, ORDER_TYPES) if not end or e.ts < end]
    seen: dict[tuple, bool] = {}
    out: dict[str, dict] = {}
    for e in evs:
        oid = e.payload.get("order_id")
        if oid and (oid, e.type) in seen:
            continue
        if oid:
            seen[(oid, e.type)] = True
        h = e.ts[11:13]
        row = out.setdefault(h, {"hour": f"{h}:00", "received": 0, "handed_off": 0, "cancelled": 0, "actions": 0, "late": 0})
        if e.type == "order.received":
            row["received"] += 1
        elif e.type == "order.handed_off":
            row["handed_off"] += 1
            if (e.payload.get("late_min") or 0) > 0:
                row["late"] += 1
        elif e.type == "order.cancelled":
            row["cancelled"] += 1
        elif e.type == "action.applied":
            row["actions"] += 1
    return [out[k] for k in sorted(out)]
