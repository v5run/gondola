"""Capacity: Savvy's reservation scheduler, generalized for the store, plus headroom over the next 30 minutes.

`schedule()` is the reservation logic of gondola/rush/engine.py `Kitchen._schedule` (same rules: work in progress is
reserved first and never moves; shared cooks; station occupancy; packing after cooking; estimates, never hidden
actual durations), generalized to what the real store needs:
  - several cook tasks per order (multi-item orders; packing waits for all of them),
  - several parallel slots per station (noodle baskets, fryer baskets) and fractional hands-on cook time,
  - an externally supplied priority order (the Present queue, or FIFO),
  - a just-in-time release: a task may start no earlier than its latest start minus the item's hold tolerance,
    unless waiting would make it late (then it starts as early as it fits: work-conserving under pressure).

`PresentKitchen` subclasses Savvy's `Kitchen` so Savvy's offer guard (`evaluate_offer` / `publish_offer`: stock,
budget, contribution floor, lead-time reserve, "would worsen an accepted order") runs unchanged against these same
reservations: connected control.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .queue import QOrder, QTask, due_of
from .world import MENU, STATIONS, hm

H = 360  # planning horizon in minutes


class Grid:
    def __init__(self, now: int, slots: dict[str, int], cooks, horizon: int = H):
        self.now, self.h = now, horizon
        self.slots = slots
        self.cooks = cooks if callable(cooks) else (lambda m, c=cooks: c)
        self.occ = {s: [0] * horizon for s in STATIONS}
        self.lab = [0.0] * horizon
        self.cap = [float(self.cooks(now + i)) for i in range(horizon)]

    def fits(self, station: str, start: int, dur: int, labour: float) -> bool:
        i0 = start - self.now
        slots = self.slots.get(station, 1)
        occ = self.occ[station]
        for i in range(i0, min(self.h, i0 + dur)):
            if occ[i] + 1 > slots:
                return False
            if labour and self.lab[i] + labour > self.cap[i] + 1e-9:
                return False
        return True

    def first_fit(self, station: str, earliest: int, dur: int, labour: float) -> int:
        s = max(self.now, earliest)
        while s - self.now + dur < self.h:
            if self.fits(station, s, dur, labour):
                return s
            s += 1
        return s

    def reserve(self, station: str, start: int, dur: int, labour: float, force: bool = False):
        i0 = start - self.now
        for i in range(max(0, i0), min(self.h, i0 + dur)):
            self.occ[station][i] += 1
            if labour:
                self.lab[i] += labour


def _dur(t: QTask, speeds: dict[str, float]) -> int:
    return max(1, math.ceil(t.remaining / max(speeds.get(t.station, 1.0), 0.1) - 1e-9))


def schedule(orders: list[QOrder], priority: list[str], now: int, speeds: dict[str, float], slots: dict[str, int],
             cooks, jit: bool = True, hold: dict[str, float] | None = None,
             buffer: float = 0.0) -> tuple[list[dict], dict[str, int]]:
    """Reserve every unfinished task. Returns (rows, finish) where rows are
    {task_id, order_id, station, start, end, item, frozen} and finish[order_id] = planned packing end."""
    g = Grid(now, slots, cooks)
    rows: list[dict] = []
    ends: dict[str, int] = {}
    by_id = {o.order_id: o for o in orders}
    # 1. work in progress never moves (Savvy's first loop)
    for o in orders:
        for t in o.tasks + ([o.pack] if o.pack else []):
            if t.started and not t.done:
                d = _dur(t, speeds)
                g.reserve(t.station, now, d, t.labour)
                ends[t.task_id] = now + d
                rows.append({"task_id": t.task_id, "order_id": o.order_id, "station": t.station, "start": t.start if t.start is not None else now,
                             "end": now + d, "item": t.item, "frozen": True})
    # 2. everything else in priority order
    for oid in priority:
        o = by_id.get(oid)
        if o is None or o.ready is not None:
            continue
        due, _ = due_of(o, now)
        pack_d = _dur(o.pack, speeds) if o.pack and not o.pack.done else 0
        cook_end = now
        for t in o.tasks:
            if t.done:
                continue
            if t.task_id in ends:
                cook_end = max(cook_end, ends[t.task_id])
                continue
            d = _dur(t, speeds)
            latest = math.floor(due - pack_d - d - buffer - 0.15 * d)   # longer tasks overrun more
            tol = (hold or {}).get(oid, t.hold)
            release = latest - tol if jit else now
            s = g.first_fit(t.station, max(now, math.ceil(o.created - 1e-9), math.floor(release)), d, t.labour)
            if jit and s > latest and release > now:
                s = min(s, g.first_fit(t.station, now, d, t.labour))
            g.reserve(t.station, s, d, t.labour)
            ends[t.task_id] = s + d
            cook_end = max(cook_end, s + d)
            rows.append({"task_id": t.task_id, "order_id": oid, "station": t.station, "start": s, "end": s + d,
                         "item": t.item, "frozen": False})
        if o.pack and not o.pack.done:
            if o.pack.task_id in ends:
                finish = ends[o.pack.task_id]
            else:
                s = g.first_fit("packing", cook_end, pack_d, 0.0)
                g.reserve("packing", s, pack_d, 0.0)
                finish = s + pack_d
                rows.append({"task_id": o.pack.task_id, "order_id": oid, "station": "packing", "start": s,
                             "end": finish, "item": None, "frozen": False})
            ends[oid] = finish
        else:
            ends[oid] = cook_end
    finish = {o.order_id: ends.get(o.order_id, now) for o in orders if o.ready is None}
    return rows, finish


# ------------------------------------------------------------------ headroom
@dataclass
class Headroom:
    pct: float                     # min over resources, percent
    binding: str                   # the resource with the least headroom
    by_resource: dict              # resource -> {capacity, reserved, forecast, pct}
    ahead_pct: float               # predicted headroom for the window starting `lookahead` minutes from now
    window_min: int
    forecast_orders: float

    def to_dict(self) -> dict:
        return {"pct": round(self.pct, 1), "binding": self.binding, "ahead_pct": round(self.ahead_pct, 1),
                "window_min": self.window_min, "forecast_orders": round(self.forecast_orders, 1),
                "by_resource": {k: {kk: round(vv, 1) for kk, vv in v.items()} for k, v in self.by_resource.items()}}


def forecast_orders(arrivals: list[dict], start: int, end: int) -> dict[str, float]:
    """Expected new orders per channel in [start, end) from 15-minute bins (prorated)."""
    out: dict[str, float] = {}
    for b in arrivals:
        t0 = b["t"]
        ov = max(0, min(end, t0 + 15) - max(start, t0))
        if ov:
            out[b["channel"]] = out.get(b["channel"], 0.0) + b["p50"] * ov / 15
    return out


def headroom(orders: list[QOrder], now: int, speeds: dict[str, float], slots: dict[str, int], cooks_at,
             arrivals: list[dict], work_per_order: dict[str, float], window: int = 30, lead: int = 10,
             lookahead: int = 20, removed: dict[str, float] | None = None) -> Headroom:
    """Headroom = capacity over the next `window` minutes - reserved (accepted, unfinished) work - forecast arrivals
    (arrivals in the last `lead` minutes of the window are not counted: their work lands after it). Per station
    (slot-minutes at current speed) and for hands-on cook time; the minimum is reported with its binding resource.
    `removed`: share of forecast work per channel taken away by an admission action (for simulate)."""
    removed = removed or {}

    def cap(t0: int) -> dict[str, float]:
        c = {s: slots.get(s, 1) * window * speeds.get(s, 1.0) for s in STATIONS}
        c["labour"] = float(sum(cooks_at(t0 + i) for i in range(window)))
        return c

    reserved = {s: 0.0 for s in STATIONS}
    reserved["labour"] = 0.0
    for o in orders:
        if o.ready is not None:
            continue
        for t in o.tasks + ([o.pack] if o.pack else []):
            if t.done:
                continue
            reserved[t.station] += t.remaining
            reserved["labour"] += t.remaining * t.labour

    def fc(t0: int, t1: int) -> tuple[dict[str, float], float]:
        per_ch = forecast_orders(arrivals, t0, t1)
        n = sum(v * (1 - removed.get(ch, 0.0)) for ch, v in per_ch.items())
        return {r: n * work_per_order.get(r, 0.0) for r in reserved}, n

    c0 = cap(now)
    f0, n0 = fc(now, now + window - lead)
    by = {}
    for r in reserved:
        pct = 100.0 * (c0[r] - reserved[r] - f0[r]) / max(c0[r], 1e-6)
        by[r] = {"capacity": c0[r], "reserved": reserved[r], "forecast": f0[r], "pct": pct}
    binding = min(by, key=lambda r: by[r]["pct"])
    # ahead: carry over what the first `lookahead` minutes can't absorb, then the next window
    c_a = cap(now + lookahead)
    f_first, _ = fc(now, now + lookahead)
    f_next, _ = fc(now + lookahead, now + lookahead + window - lead)
    ahead = []
    for r in reserved:
        cap_first = c0[r] * lookahead / window
        carry = max(0.0, reserved[r] + f_first[r] - cap_first)
        ahead.append(100.0 * (c_a[r] - carry - f_next[r]) / max(c_a[r], 1e-6))
    return Headroom(by[binding]["pct"], binding, by, min(ahead), window, n0)


# ------------------------------------------------------------------ Savvy's offer guard on these reservations
RUSH_TO_ITEM = {"tonkotsu": "Tonkotsu", "karaage": "Karaage", "gyoza": "Gyoza", "don": "Chashu Don"}


def present_kitchen(orders: list[QOrder], priority: list[str], now: int, speeds: dict[str, float],
                    slots: dict[str, int], cooks_at, budget_cents: int, spent_cents: int, discount_cents: int,
                    stock: dict[str, int], forecast_pressure: float = 1.0):
    """Build a gondola.rush Kitchen whose reservation function is Present's (connected control). Savvy's
    evaluate_offer / publish_offer then run unchanged. Imported lazily so gondola.rush stays optional here."""
    from ..rush.engine import Kitchen, Order, Task
    from ..rush.models import OfferPolicy, RushRequest

    class PresentKitchen(Kitchen):
        def _schedule(self, extra=None):
            qs = list(orders)
            prio = list(priority)
            if extra is not None:
                q = QOrder(extra.id, extra.channel, "pickup", float(extra.created), float(extra.promise),
                           items=[RUSH_TO_ITEM.get(extra.item, extra.item)])
                for t in extra.tasks:
                    item = RUSH_TO_ITEM.get(extra.item, extra.item)
                    qt = QTask(t.id, item if t.station != "packing" else None, t.station, float(t.nominal),
                               labour=MENU.get(item, {}).get("labour", 0.0) if t.station != "packing" else 0.0,
                               hold=MENU.get(item, {}).get("hold", 60.0))
                    if t.station == "packing":
                        q.pack = qt
                    else:
                        q.tasks.append(qt)
                qs.append(q)
                prio.append(q.order_id)   # new first-party visitors come after accepted work (Savvy's rule)
            rows, _ = schedule(qs, prio, self.minute, speeds, slots, cooks_at)
            return rows

    req = RushRequest(budget_cents=max(0, min(5000, budget_cents)), cooks=4,
                      forecast_pressure=max(0.25, min(2.0, forecast_pressure)),
                      policy=OfferPolicy(discount_cents=discount_cents))
    k = PresentKitchen(req, "coordinated")
    k.minute = now
    k.spent = spent_cents
    k.speed = {s: speeds.get(s, 1.0) for s in STATIONS}
    k.stock = {key: int(stock.get(item, 40)) for key, item in RUSH_TO_ITEM.items()}
    k.estimates = {key: float(MENU[item]["minutes"]) for key, item in RUSH_TO_ITEM.items()}
    # Accepted work, in Savvy's Order shape, so "would worsen an accepted order" is checked on the real queue.
    k.orders = []
    for o in orders:
        if o.ready is not None:
            continue
        so = Order(o.order_id, o.channel, "tonkotsu", int(o.created), int(o.promise), None)
        so.tasks = [Task(t.task_id, o.order_id, t.station, t.remaining) for t in o.tasks + ([o.pack] if o.pack else [])]
        k.orders.append(so)
    return k


def guard_offer(kitchen, key: str, discount_cents: int, slots: dict[str, int]) -> dict:
    """Savvy's evaluate_offer, with one adaptation: its station-load check assumes one slot per station, so a
    multi-slot station's load is divided by its slot count before applying the same policy limit."""
    check = kitchen.evaluate_offer(key, discount_cents)
    if not check.get("allowed") and check.get("reason") == "Station load exceeds the policy limit":
        n = max(1, slots.get(check["station"], 1))
        load = check["station_load"] / n
        if load <= kitchen.policy.max_station_load:
            check = {**check, "allowed": True, "station_load": round(load, 3),
                     "reason": "Fits shared station, cook, stock and promise reservations"}
    elif check.get("station_load") is not None:
        check = {**check, "station_load": round(check["station_load"] / max(1, slots.get(check.get("station"), 1)), 3)}
    check["item_name"] = RUSH_TO_ITEM.get(key, key)
    return check
