"""One queue for every platform: what to cook next (design TRI_WORKFLOW.md section 3.2).

For each order:
  due          = earliest of the customer promise, the courier's ETA (delivery) and "now" if the guest is in the store
  latest_start = due - remaining work (critical path of unfinished cook tasks + packing, at current station speeds)
  slack        = latest_start - now
The queue is ordered by slack plus named, per-store-weighted adjustments (minutes; negative = sooner):
  courier   far courier (ETA after the promise) adds capped slack; a courier arriving/here removes slack
  distance  long customer drives finish closer to pickup (small extra slack per km beyond 3 km)
  hold      items that can't wait (fried, noodles) start later when there is slack; rice bowls can go early
  weather   rain/snow: ETA-uncertainty buffer for delivery (be ready earlier); cold tightens hold tolerance
  batch     same-station, same-item work due within the batching window is pulled together
  fairness  no order waits past max_wait_min (Savvy's age protection: target = min(due, created + max) )
  in_store  a guest physically in the store gets a bump. Channel itself never buys priority.
Orders at risk (slack <= urgent_slack_min, or past the fairness cap) form the first tier, ordered by slack: the bumps
only reorder orders that still have room, so they never push an at-risk order past its latest start.
Work in progress is frozen; next-up work keeps its place unless beaten by `reshuffle_margin_min` (limited churn).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .world import MENU, hm

FACTORS = ("courier", "distance", "hold", "weather", "batch", "fairness", "in_store")


@dataclass
class QTask:
    task_id: str
    item: str | None
    station: str
    remaining: float           # planned minutes of work left at speed 1.0
    labour: float = 0.0        # hands-on cook share while it runs
    hold: float = 60.0         # minutes the item can wait once cooked
    started: bool = False
    done: bool = False
    start: int | None = None   # actual start minute (frozen) if started


@dataclass
class QOrder:
    order_id: str
    channel: str
    fulfillment: str           # delivery | pickup | dine_in
    created: float
    promise: float
    items: list[str] = field(default_factory=list)
    tasks: list[QTask] = field(default_factory=list)        # cook tasks
    pack: QTask | None = None
    courier_eta: float | None = None
    courier_arrived: bool = False
    courier_distance_km: float | None = None
    customer_distance_km: float | None = None
    customer_present: bool = False
    ready: float | None = None

    @property
    def status(self) -> str:
        if self.ready is not None:
            return "ready"
        if self.pack and self.pack.started:
            return "packing"
        if any(t.started for t in self.tasks):
            return "cooking"
        return "queued"


def make_task(task_id: str, item: str | None, station: str, minutes: float, **kw) -> QTask:
    m = MENU.get(item or "", {})
    return QTask(task_id, item, station, minutes, labour=kw.pop("labour", m.get("labour", 0.0) if station != "packing" else 0.0),
                 hold=kw.pop("hold", m.get("hold", 60.0)), **kw)


def remaining_work(o: QOrder, speeds: dict[str, float]) -> float:
    """Critical path: cook tasks run in parallel on their stations, then packing."""
    cook = max([t.remaining / max(speeds.get(t.station, 1.0), 0.1) for t in o.tasks if not t.done] or [0.0])
    pack = 0.0
    if o.pack and not o.pack.done:
        pack = o.pack.remaining / max(speeds.get("packing", 1.0), 0.1)
    return cook + pack


def hold_tolerance(o: QOrder, weather: dict, w) -> float:
    tol = min([t.hold for t in o.tasks if not t.started and not t.done] or [60.0])
    temp = (weather or {}).get("temp_c")
    if temp is not None and temp < w.cold_temp_c and o.fulfillment != "dine_in":
        tol *= w.cold_hold_factor
    return tol


def due_of(o: QOrder, now: float) -> tuple[float, str]:
    due, src = float(o.promise), "promise"
    if o.fulfillment == "delivery" and o.courier_eta is not None and o.courier_eta < due:
        due, src = float(o.courier_eta), "courier ETA"
    if o.customer_present and o.fulfillment == "pickup" and now < due:
        due, src = float(now), "guest here"
    if o.courier_arrived and now < due:
        due, src = float(now), "courier here"
    return due, src


def score(o: QOrder, now: float, speeds: dict[str, float], weather: dict, settings, batch_ids: set | None = None,
          next_up: set | None = None) -> dict:
    w = settings.weights
    due, due_src = due_of(o, now)
    rem = remaining_work(o, speeds)
    latest = due - rem
    slack = latest - now
    f = {k: 0.0 for k in FACTORS}
    notes: list[tuple[float, str]] = []
    # courier
    if o.fulfillment == "delivery":
        if o.courier_arrived or (o.courier_eta is not None and o.courier_eta - now <= 2):
            f["courier"] = -w.courier * w.courier_arriving_min
            notes.append((abs(f["courier"]) + 2, "courier here" if o.courier_arrived else f"courier arriving {hm(o.courier_eta)}"))
        elif o.courier_eta is not None and o.courier_eta > o.promise:
            f["courier"] = w.courier * min(o.courier_eta - o.promise, w.courier_far_cap_min)
            km = f" ({o.courier_distance_km:.1f} km)" if o.courier_distance_km is not None else ""
            notes.append((f["courier"], f"courier far{km}, ETA {hm(o.courier_eta)}"))
        elif o.courier_eta is None:
            notes.append((0.1, "no courier assigned yet"))
    # customer distance (delivery drive)
    if o.fulfillment == "delivery" and o.customer_distance_km is not None:
        f["distance"] = w.distance * max(0.0, o.customer_distance_km - 3.0)
        if f["distance"] >= 1:
            notes.append((f["distance"], f"long drive ({o.customer_distance_km:.1f} km): finish close to pickup"))
    # hold tolerance
    tol = hold_tolerance(o, weather, w)
    if slack > 0:
        f["hold"] = w.hold * min(slack, max(0.0, 10.0 - tol)) * 0.5
        if f["hold"] >= 1:
            notes.append((f["hold"], "can't wait once cooked: start later"))
    # weather: courier ETA uncertainty buffer
    if o.fulfillment == "delivery" and weather:
        buf = (w.snow_buffer_min if weather.get("snow") else w.rain_buffer_min if weather.get("rain") else 0.0)
        f["weather"] = -w.weather * buf
        if buf:
            notes.append((abs(f["weather"]) * 0.5, f"{'snow' if weather.get('snow') else 'rain'}: ETA buffer"))
    # batching
    if batch_ids and o.order_id in batch_ids:
        f["batch"] = -w.batch * 1.0
        notes.append((0.5, "batched with same-item work"))
    # fairness cap (Savvy: min(target - remaining, created + max_age - remaining))
    age_latest = o.created + settings.max_wait_min - rem
    if age_latest < latest:
        f["fairness"] = -w.fairness * (latest - age_latest)
        notes.append((abs(f["fairness"]) + 5, f"waiting {now - o.created:.0f} min: fairness cap {settings.max_wait_min} min"))
    # guest in the store
    if o.customer_present or o.fulfillment == "dine_in":
        f["in_store"] = -w.in_store
        notes.append((w.in_store, "guest in the store" if o.fulfillment == "dine_in" else "pickup guest waiting"))
    priority = slack + sum(f.values())
    if next_up and o.order_id in next_up:
        priority -= w.reshuffle_margin_min
    # At-risk orders come first, ordered by slack plus the fairness cap only: no bump can push them past their start.
    urgent = slack <= w.urgent_slack_min or f["fairness"] < 0
    tier = 0 if urgent else 1
    if urgent:
        priority = slack + f["fairness"]
    if slack < 0:
        notes.append((abs(slack) + 3, f"behind by {-slack:.0f} min"))
    notes.sort(key=lambda x: -x[0])
    head = f"{slack:+.0f} min slack, due {hm(due)} ({due_src})"
    reason = head + ("; " + ", ".join(t for _, t in notes[:2]) if notes else "")
    return {"order_id": o.order_id, "due": due, "due_source": due_src, "remaining_min": round(rem, 2),
            "latest_start": latest, "slack_min": round(slack, 2), "factors": {k: round(v, 2) for k, v in f.items()},
            "priority": round(priority, 3), "tier": tier, "hold_tolerance": tol, "reason": reason}


def batch_groups(orders: list[QOrder], scores: dict[str, dict], window: float) -> tuple[set, dict]:
    """Orders with an unstarted task of the same item whose latest starts fall within `window` minutes."""
    by_item: dict[str, list[tuple[float, str]]] = {}
    for o in orders:
        for t in o.tasks:
            if not t.started and not t.done and t.item:
                by_item.setdefault(t.item, []).append((scores[o.order_id]["latest_start"], o.order_id))
    ids, groups = set(), {}
    for item, rows in by_item.items():
        rows.sort()
        for i, (ls, oid) in enumerate(rows):
            near = [x for x in rows if x[1] != oid and abs(x[0] - ls) <= window]
            if near:
                ids.add(oid)
                groups.setdefault(oid, f"{item}@{hm(min(ls, near[0][0]))}")
    return ids, groups


def rank(orders: list[QOrder], now: float, speeds: dict[str, float], weather: dict, settings,
         next_up: set | None = None) -> list[dict]:
    """Ranked queue of the active (not handed-off) orders, most urgent first. Ties: created time, then id
    (never channel)."""
    active = [o for o in orders if o.ready is None]
    first = {o.order_id: score(o, now, speeds, weather, settings) for o in active}
    ids, groups = batch_groups(active, first, settings.weights.batch_window_min) if settings.weights.batch else (set(), {})
    out = []
    for o in active:
        s = score(o, now, speeds, weather, settings, ids, next_up) if (ids or next_up) else first[o.order_id]
        s["batch_group"] = groups.get(o.order_id)
        s["status"] = o.status
        out.append((s["tier"], s["priority"], o.created, o.order_id, s))
    out.sort(key=lambda x: x[:4])
    return [dict(s, rank=i + 1) for i, (_, _, _, _, s) in enumerate(out)]


def fifo_rank(orders: list[QOrder]) -> list[str]:
    return [o.order_id for o in sorted((o for o in orders if o.ready is None), key=lambda o: (o.created, o.order_id))]
