"""A minute-step, reproducible experiment, not a live merchant integration.

The controller receives only accepted work, observed progress/ETAs/speeds and a
declared forecast. Actual future arrivals, task durations and buyer utilities
belong to the evaluator. Campaign checks and scheduling share one reservation
function. All policies see the same exogenous draws for a given seed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import OfferPolicy, RushRequest

MENU = {
    "tonkotsu": {"name": "Tonkotsu ramen", "station": "noodles", "minutes": 4, "price": 1925, "cost": 620, "stock": 55},
    "karaage": {"name": "Chicken karaage", "station": "fryer", "minutes": 5, "price": 1450, "cost": 330, "stock": 45},
    "gyoza": {"name": "Crispy gyoza", "station": "fryer", "minutes": 3, "price": 950, "cost": 240, "stock": 45},
    "don": {"name": "Chashu rice bowl", "station": "assembly", "minutes": 2, "price": 1540, "cost": 510, "stock": 40},
}
STATIONS = ["fryer", "noodles", "assembly", "packing"]
MODES = {"fifo": "FIFO", "deadline": "Earliest promise", "slack": "Remaining slack", "independent": "Separate campaigns", "coordinated": "Connected control"}
CHANNELS = ["doordash", "ubereats", "pickup"]
FEES = {"doordash": 0.25, "ubereats": 0.25, "pickup": 0.03}
HORIZON = 45


def clock(minute: int | float) -> str:
    n = 17 * 60 + 30 + int(minute)
    return f"{n // 60:02}:{n % 60:02}"


@dataclass
class Task:
    id: str
    order_id: str
    station: str
    nominal: float
    start: int | None = None
    end: int | None = None
    progress: float = 0.0


@dataclass
class Order:
    id: str
    channel: str
    item: str
    created: int
    promise: int
    eta: int | None
    origin: str = "accepted"
    discount: int = 0
    ready: int | None = None
    tasks: list[Task] = field(default_factory=list)


def _world(req: RushRequest) -> dict:
    """All random draws are separate from controller calls and policy choices."""
    rng = random.Random(req.seed)
    count = 27 if req.scenario != "overload" else 42
    initial = []
    for i in range(count):
        ch = "doordash" if i < 12 else "ubereats" if i < 22 else "pickup"
        if req.scenario == "balanced":
            item = rng.choice(list(MENU))
        elif req.scenario == "quiet":
            item = rng.choice(["tonkotsu", "don", "karaage"])
        else:
            item = rng.choices(list(MENU), [0.30, 0.18, 0.20, 0.32])[0]
        created = rng.randint(0, 8) if req.scenario != "quiet" else rng.randint(0, 30)
        promise = created + (rng.randint(15, 35) if ch == "pickup" else rng.randint(28, 55))
        eta = promise + rng.randint(-3, 3) if ch != "pickup" else None
        initial.append({"id": f"{ch[:2].upper()}-{101+i}", "channel": ch, "item": item, "created": created,
                        "promise": promise, "eta": eta})
    if req.scenario == "quiet":
        initial = initial[:10]
    buyers = []
    for i, minute in enumerate(range(10, 40, 2)):
        buyers.append({"id": f"WEB-{201+i}", "minute": minute,
                       "utility": {k: rng.uniform(-1, 0.8) + (0.3 if k == "karaage" else 0) for k in MENU},
                       "sensitivity": rng.uniform(0.8, 1.8), "threshold": rng.uniform(0.45, 1.0)})
    # Hash-based per-task noise avoids policy-dependent consumption of RNG state.
    return {"orders": sorted(initial, key=lambda o: (o["created"], o["id"])), "buyers": buyers}


class Kitchen:
    def __init__(self, req: RushRequest, mode: str = "coordinated"):
        if mode not in MODES:
            raise ValueError("unknown controller")
        self.req, self.mode, self.policy = req, mode, req.policy
        self._world = _world(req)
        self.minute = 0
        self.orders: list[Order] = []
        self.stock = {k: v["stock"] for k, v in MENU.items()}
        self.speed = {k: 1.0 for k in STATIONS}
        self.blocked_until: dict[str, int] = {}
        self.estimates = {k: float(v["minutes"]) for k, v in MENU.items()}
        self.samples = {k: 0 for k in MENU}
        self.errors: list[dict] = []
        self.spent = 0
        self.offer: dict | None = None
        self.actions: list[dict] = []
        self.events: list[dict] = []
        self.frames: list[dict] = []
        self.current_plan: list[dict] = []
        self._truth_work: dict[str, float] = {}
        self._arrival_truth: dict[str, int] = {}
        self._previous_starts: dict[str, int] = {}
        self.churn = 0
        self.declined_visitors = 0
        self.buyer_choices: list[dict] = []

    def _accept(self, data: dict, origin: str = "accepted", discount: int = 0):
        item = data["item"]
        if self.stock[item] <= 0:
            return False
        self.stock[item] -= 1
        o = Order(**data, origin=origin, discount=discount)
        o.tasks = [Task(o.id + ":cook", o.id, MENU[item]["station"], self.estimates[item]),
                   Task(o.id + ":pack", o.id, "packing", 1)]
        for t in o.tasks:
            digest = hashlib.sha256(f"{self.req.seed}:{t.id}".encode()).digest()
            factor = 0.85 + digest[0] / 255 * 0.35
            self._truth_work[t.id] = MENU[item]["minutes"] * factor if t.station != "packing" else 1.0
        self._arrival_truth[o.id] = o.eta if o.eta is not None else o.promise
        self.orders.append(o)
        return True

    def observe(self) -> dict:
        """Public agent/controller state; deliberately no world/buyer/future truth."""
        return {"minute": self.minute, "clock": clock(self.minute), "source_mode": "synthetic",
                "orders": [{"id": o.id, "channel": o.channel, "item": o.item, "created": o.created,
                            "promise": o.promise, "eta": o.eta, "origin": o.origin, "ready": o.ready,
                            "tasks": [asdict(t) for t in o.tasks]} for o in self.orders],
                "stock": dict(self.stock), "station_speed": dict(self.speed), "blocked_until": dict(self.blocked_until),
                "estimated_cook_minutes": dict(self.estimates), "completed_samples": dict(self.samples),
                "budget_remaining_cents": self.req.budget_cents - self.spent,
                "cooks": self.req.cooks,
                "forecast": {"source": "declared scenario plus configurable forecast reserve", "expected_visitors_next_10m": round(5 * self.req.forecast_pressure, 1),
                             "context": "Evening event and rain" if self.req.scenario == "rush" else self.req.scenario,
                             "uncertainty": "Customer response and task durations are modeled, not merchant measurements"}}

    def _schedule(self, extra: Order | None = None) -> list[dict]:
        """List reservations: shared cooks, station occupancy, task dependencies.

        Work in progress is frozen. Estimates, not private future durations, are
        used. This is a heuristic schedule, not a claim of global optimality.
        """
        now = self.minute
        occ = {s: [0] * 500 for s in STATIONS}
        labour = [0] * 500
        rows: list[dict] = []
        work = self.orders + ([extra] if extra else [])
        ends: dict[str, int] = {}
        for s, until in self.blocked_until.items():
            for m in range(now, min(until, 500)):
                occ[s][m] = 1

        def reserve(t: Task, start: int, duration: int, item: str):
            end = min(499, start + duration)
            for m in range(start, end):
                occ[t.station][m] += 1
                if t.station != "packing":
                    labour[m] += 1
            ends[t.id] = end
            rows.append({"task_id": t.id, "order_id": t.order_id, "station": t.station,
                         "start": start, "end": end, "item": item, "frozen": t.start is not None})

        for o in work:
            for t in o.tasks:
                if t.end is not None:
                    ends[t.id] = t.end
                elif t.start is not None:
                    remaining = max(1, math.ceil((t.nominal - t.progress) / max(self.speed[t.station], 0.1)))
                    remaining += max(0, self.blocked_until.get(t.station, now) - now)
                    reserve(t, now, remaining, o.item)

        def remaining(o: Order):
            return sum(max(0, t.nominal - t.progress) / max(self.speed[t.station], 0.1) for t in o.tasks if t.end is None)

        def key(o: Order):
            if self.mode == "fifo":
                return (0, o.created, o.id)
            # New first-party visitors get spare reservations after the rush's
            # accepted commitments. Earlier visitor bookings remain ahead of
            # later ones. The same discipline is used by both campaign arms.
            if o.origin == "visitor":
                return (1, o.created, o.id)
            if self.mode == "deadline":
                return (0, o.promise, o.created, o.id)
            # Customer promise caps the courier target; moving an ETA cannot erase lateness.
            target = min(o.promise, o.eta) if o.eta is not None else o.promise
            age_protection = o.created + 35
            return (0, min(target - remaining(o), age_protection - remaining(o)), o.created, o.id)

        for o in sorted((o for o in work if o.ready is None), key=key):
            target = min(o.promise, o.eta) if o.eta is not None else o.promise
            # Work-conserving reservation avoids a receding just-in-time plan
            # repeatedly deferring preparation under pressure.
            floor = now
            for t in o.tasks:
                if t.id in ends:
                    continue
                earliest = now if t.station == "packing" else floor
                if t.station == "packing":
                    earliest = max(earliest, ends.get(o.id + ":cook", now))
                duration = max(1, math.ceil(t.nominal / max(self.speed[t.station], 0.1)))
                start = earliest
                while start + duration < 499:
                    if all(occ[t.station][m] < 1 and (t.station == "packing" or labour[m] < self.req.cooks)
                           for m in range(start, start + duration)):
                        break
                    start += 1
                reserve(t, start, duration, o.item)
        return rows

    def _finish_by(self, plan: list[dict]) -> dict[str, int]:
        return {r["order_id"]: r["end"] for r in plan if r["station"] == "packing"}

    def evaluate_offer(self, item: str, discount_cents: int | None = None) -> dict:
        if item not in MENU:
            return {"allowed": False, "reason": "Unknown approved menu item"}
        discount = self.policy.discount_cents if discount_cents is None else discount_cents
        if type(discount) is not int or not 0 <= discount <= 200:
            return {"item": item, "allowed": False, "reason": "Discount exceeds the fixed owner limit"}
        info = MENU[item]
        margin = info["price"] - info["cost"] - round(info["price"] * FEES["pickup"]) - discount
        reason = None
        if not 0 <= discount <= 200:
            reason = "Discount exceeds the fixed owner limit"
        elif self.stock[item] < 2:
            reason = "Insufficient unreserved stock"
        elif discount > self.req.budget_cents - self.spent:
            reason = "Campaign budget exhausted"
        elif margin < self.policy.minimum_margin_cents:
            reason = "Contribution below the policy floor"
        base = self._schedule()
        promise = self.minute + 15
        probe = Order("PROBE", "pickup", item, self.minute, promise, None, origin="visitor")
        probe.tasks = [Task("PROBE:cook", "PROBE", info["station"], self.estimates[item]), Task("PROBE:pack", "PROBE", "packing", 1)]
        proposed = self._schedule(probe)
        before, after = self._finish_by(base), self._finish_by(proposed)
        protected = [o for o in self.orders if o.ready is None]
        worsened = [o.id for o in protected if max(0, after.get(o.id, 499) - o.promise) > max(0, before.get(o.id, 499) - o.promise)]
        finish = after.get("PROBE", 499)
        end = self.minute + 15
        station_busy = sum(max(0, min(end, r["end"]) - max(self.minute, r["start"])) for r in base if r["station"] == info["station"])
        load = station_busy / 15
        if not reason and worsened:
            reason = "Would worsen an accepted order's predicted lateness"
        reserve = math.ceil(self.policy.reserve_minutes * self.req.forecast_pressure)
        if not reason and finish > promise - reserve:
            reason = "Insufficient lead-time reserve for the new order"
        if not reason and load > self.policy.max_station_load:
            reason = "Station load exceeds the policy limit"
        return {"item": item, "name": info["name"], "allowed": reason is None,
                "reason": reason or "Fits shared station, cook, stock and promise reservations",
                "discount_cents": discount, "contribution_cents": margin,
                "station": info["station"], "station_load": round(load, 3),
                "predicted_ready_minute": finish, "promise_minute": promise,
                "forecast_reserve_minutes": reserve,
                "affected_commitments": worsened,
                "score": round(margin / 100 - self.policy.load_weight * load, 3),
                "limits": "Feasibility uses current observations and estimated durations; future disruptions can cause misses"}

    def offers(self) -> list[dict]:
        return [self.evaluate_offer(k) for k in MENU]

    def publish_offer(self, item: str | None, discount: int | None = None, source: str = "controller") -> dict:
        if item is None:
            self.offer = None
            receipt = {"status": "applied", "action": "pause_offer", "source_mode": "simulation", "minute": self.minute, "source": source}
        else:
            check = self.evaluate_offer(item, discount)
            if not check["allowed"]:
                return {"status": "rejected", "source_mode": "simulation", "minute": self.minute, "evidence": check}
            self.offer = {"item": item, "discount_cents": check["discount_cents"], "until": self.minute + 5, "source": source}
            receipt = {"status": "applied", "action": "feature_item", "source_mode": "simulation", "minute": self.minute,
                       "source": source, "item": item, "discount_cents": check["discount_cents"], "evidence": check}
        receipt["receipt_id"] = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()[:12]
        self.actions.append(receipt)
        return receipt

    def _campaign(self):
        if self.mode not in ("independent", "coordinated") or not 10 <= self.minute < 40:
            self.offer = None
            return
        # An agent-published lease is rechecked each tick and never overrides the guard.
        if self.offer and self.offer["source"] == "gemini" and self.minute < self.offer["until"]:
            check = self.evaluate_offer(self.offer["item"], self.offer["discount_cents"])
            if check["allowed"]:
                return
            self.publish_offer(None, source="safety_check")
        if self.minute % 5 and self.offer and self.minute < self.offer["until"]:
            if self.mode == "independent" or self.evaluate_offer(self.offer["item"], self.offer["discount_cents"])["allowed"]:
                return
        candidates = self.offers()
        if self.mode == "independent":
            # Stronger than random marketing: stock + budget + margin; no kitchen reservations.
            candidates = [c for c in candidates if self.stock[c["item"]] >= 2 and c["discount_cents"] <= self.req.budget_cents - self.spent and c["contribution_cents"] >= self.policy.minimum_margin_cents]
            best = max(candidates, key=lambda c: c["contribution_cents"], default=None)
            selected = {"item": best["item"], "discount_cents": best["discount_cents"], "until": self.minute + 5, "source": "independent"} if best else None
            if selected and (not self.offer or self.offer["item"] != selected["item"]):
                self.actions.append({"status": "applied", "action": "feature_item", "source_mode": "simulation", "source": "independent", "minute": self.minute, **selected})
            self.offer = selected
        else:
            best = max((c for c in candidates if c["allowed"]), key=lambda c: c["score"], default=None)
            new_item = best["item"] if best else None
            old_item = self.offer["item"] if self.offer else None
            if old_item != new_item:
                self.publish_offer(new_item)
            elif self.offer:
                self.offer["until"] = self.minute + 5

    def _observe_incident(self):
        m = self.minute
        if m == self.req.incident_at and self.req.incident != "none":
            kind = self.req.incident
            if kind == "fryer_slowdown":
                self.speed["fryer"] = 0.5
                text = "Fryer capacity halved. Rechecking accepted work and offers."
            elif kind == "station_outage":
                self.blocked_until["fryer"] = m + 8
                text = "Fryer unavailable for eight modeled minutes. Work in progress stays assigned."
            else:
                for o in self.orders:
                    if o.channel == "doordash" and o.ready is None:
                        o.eta = (o.eta or o.promise) + 8
                        self._arrival_truth[o.id] += 8
                text = "DoorDash courier estimates moved eight minutes later; original promises stay fixed."
            self.events.append({"minute": m, "kind": kind, "text": text, "source_mode": "simulation"})

    def _buyers(self):
        for buyer in self._world["buyers"]:
            if buyer["minute"] != self.minute:
                continue
            scores = dict(buyer["utility"])
            if self.offer:
                scores[self.offer["item"]] += 0.55 + buyer["sensitivity"] * self.offer["discount_cents"] / 100
            available = [k for k in MENU if self.stock[k] > 0]
            item = max(available, key=lambda k: scores[k], default=None)
            if item is None or scores[item] < buyer["threshold"]:
                self.declined_visitors += 1
                self.buyer_choices.append({"minute": self.minute, "outcome": "no_order"})
                continue
            discount = self.offer["discount_cents"] if self.offer and item == self.offer["item"] else 0
            # Redemption guards are atomic: no negative budget, no unvalidated live write.
            if discount > self.req.budget_cents - self.spent:
                discount = 0
            if self.mode == "coordinated" and discount and not self.evaluate_offer(item, discount)["allowed"]:
                self.publish_offer(None, source="redemption_check")
                self.declined_visitors += 1
                continue
            data = {"id": buyer["id"], "channel": "pickup", "item": item, "created": self.minute, "promise": self.minute + 15, "eta": None}
            if self._accept(data, "visitor", discount):
                self.spent += discount
                self.buyer_choices.append({"minute": self.minute, "outcome": "order", "item": item, "discount_cents": discount})

    def step(self, forced: dict | None = None):
        now = self.minute
        self._observe_incident()
        for data in self._world["orders"]:
            if data["created"] == now:
                self._accept(data)
        self._campaign()
        if forced is not None:
            self.publish_offer(forced.get("item"), forced.get("discount_cents"), source="gemini")
        # Show the same decision boundary exposed to the agent: this minute's
        # observed incidents/orders, before its private customer-response draw.
        self.current_plan = self._schedule()
        self.frames.append(self.frame())
        self._buyers()
        plan = self._schedule()
        starts = {r["task_id"]: r["start"] for r in plan if not r["frozen"]}
        self.churn += sum(1 for tid, t in starts.items() if tid in self._previous_starts and abs(t - self._previous_starts[tid]) > 1)
        self._previous_starts = starts
        self.current_plan = plan
        task_map = {t.id: (o, t) for o in self.orders for t in o.tasks}
        for row in plan:
            o, task = task_map[row["task_id"]]
            if task.start is None and row["start"] == now:
                task.start = now
        for o in self.orders:
            for task in o.tasks:
                if task.start is None or task.end is not None:
                    continue
                if self.blocked_until.get(task.station, 0) > now:
                    continue
                task.progress += self.speed[task.station]
                if task.progress + 1e-9 >= self._truth_work[task.id]:
                    task.end = now + 1
                    if task.station == "packing":
                        o.ready = now + 1
                    else:
                        # Learn only from an observed completion, not evaluator truth.
                        observed = task.progress
                        old = self.estimates[o.item]
                        self.samples[o.item] += 1
                        self.estimates[o.item] = round(0.75 * old + 0.25 * observed, 3)
                        self.errors.append({"minute": now + 1, "item": o.item, "estimated_work": round(task.nominal, 2), "observed_work": round(observed, 2), "updated_estimate": self.estimates[o.item]})
        self.minute += 1

    def frame(self) -> dict:
        plan = self.current_plan or self._schedule()
        projected = self._finish_by(plan)
        stations = []
        for s in STATIONS:
            active = [t for o in self.orders for t in o.tasks if t.station == s and t.start is not None and t.end is None]
            load = sum(max(0, min(self.minute + 15, r["end"]) - max(self.minute, r["start"])) for r in plan if r["station"] == s) / 15
            stations.append({"id": s, "load": round(min(2, load), 3), "speed": self.speed[s], "active": [t.order_id for t in active], "blocked": self.blocked_until.get(s, 0) > self.minute})
        return {"minute": self.minute, "clock": clock(self.minute), "stations": stations,
                "orders": [{"id": o.id, "channel": o.channel, "item": o.item, "created": o.created, "promise": o.promise,
                            "eta": o.eta, "origin": o.origin, "ready": o.ready, "predicted_ready": projected.get(o.id, o.ready),
                            "state": "ready" if o.ready is not None else "cooking" if any(t.start is not None for t in o.tasks) else "queued"} for o in self.orders],
                "plan": plan, "offer": copy.deepcopy(self.offer), "offer_checks": self.offers(), "spent_cents": self.spent,
                "events": copy.deepcopy(self.events), "actions": copy.deepcopy(self.actions[-8:]),
                "learning": copy.deepcopy(self.errors[-4:]), "stock": dict(self.stock)}

    def result(self) -> dict:
        completed = [o for o in self.orders if o.ready is not None]
        existing = [o for o in self.orders if o.origin == "accepted"]
        late = [o for o in completed if o.ready > o.promise]
        waits = [max(0, o.ready - self._arrival_truth[o.id]) for o in completed]
        courier_waits = [max(0, o.ready - self._arrival_truth[o.id]) for o in completed if o.channel != "pickup"]
        pickup_waits = [max(0, o.ready - self._arrival_truth[o.id]) for o in completed if o.channel == "pickup"]
        holds = [max(o.ready, self._arrival_truth[o.id]) - o.tasks[0].end for o in completed]
        contribution = sum(MENU[o.item]["price"] - MENU[o.item]["cost"] - round(MENU[o.item]["price"] * FEES[o.channel]) - o.discount for o in completed)
        lateness = sum(max(0, o.ready - o.promise) for o in completed)
        unresolved = len(self.orders) - len(completed)
        metrics = {"accepted": len(self.orders), "completed": len(completed), "unresolved": unresolved,
                   "on_time": len(completed) - len(late), "late": len(late), "existing_orders": len(existing),
                   "existing_on_time": sum(o.ready is not None and o.ready <= o.promise for o in existing),
                   "visitor_orders": sum(o.origin == "visitor" for o in self.orders),
                   "contribution_cents": contribution, "promo_spend_cents": self.spent,
                   "courier_wait_minutes": sum(courier_waits), "avg_courier_wait_minutes": round(sum(courier_waits) / max(1, len(courier_waits)), 2),
                   "worst_pickup_wait_minutes": max(pickup_waits or [0]), "avg_wait_minutes": round(sum(waits) / max(1, len(waits)), 2),
                   "food_hold_minutes": sum(holds), "worst_lateness_minutes": max([max(0, o.ready - o.promise) for o in completed] or [0]),
                   "late_minutes": lateness, "schedule_changes": self.churn,
                   "by_channel": {ch: {"accepted": sum(o.channel == ch for o in self.orders), "late": sum(o.channel == ch for o in late)} for ch in CHANNELS}}
        # Fixed declared evaluation proxy, not real profit or a model-editable objective.
        metrics["service_score"] = round(contribution / 100 - lateness * 0.6 - sum(holds) * 0.08 - unresolved * 100, 2)
        return {"mode": self.mode, "label": MODES[self.mode], "source_mode": "synthetic", "metrics": metrics,
                "frames": self.frames, "learning": self.errors,
                "actual_tasks": [{"task_id": t.id, "order_id": o.id, "station": t.station, "start": t.start, "end": t.end} for o in self.orders for t in o.tasks],
                "actions": self.actions, "buyer_outcomes": self.buyer_choices,
                "policy": self.policy.model_dump(), "menu": MENU}


def simulate(req: RushRequest, mode: str = "coordinated", forced: dict | None = None, at: int = 12) -> dict:
    kitchen = Kitchen(req, mode)
    for _ in range(350):
        kitchen.step(forced if forced is not None and kitchen.minute == at else None)
        if kitchen.minute >= HORIZON and all(o.ready is not None for o in kitchen.orders):
            break
    kitchen.frames.append(kitchen.frame())
    return kitchen.result()


def snapshot(req: RushRequest, minute: int) -> Kitchen:
    kitchen = Kitchen(req)
    for _ in range(minute):
        kitchen.step()
    # Observe this minute's incident/orders before a tool-using decision, without buyers or future task outcomes.
    kitchen._observe_incident()
    for data in kitchen._world["orders"]:
        if data["created"] == minute:
            kitchen._accept(data)
    return kitchen


def compare(req: RushRequest, forced: dict | None = None, at: int = 12) -> dict:
    runs = {mode: simulate(req, mode, forced if mode == "coordinated" else None, at) for mode in MODES}
    return {"request": req.model_dump(), "source_mode": "synthetic", "runs": runs,
            "assumptions": {"customer_response": "Fixed seeded synthetic utilities; not a conversion estimate", "fees": FEES,
                            "costs": "Explicit demo menu costs, not merchant contracts", "forecast": "Synthetic event/weather context",
                            "eta": "External modeled arrivals; dispatch feedback is not modeled", "scoring": "Contribution minus declared lateness/holding penalties; not profit"}}
