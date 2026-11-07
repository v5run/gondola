"""The live Present service for a business date, driven by the real clock (gondola.now).

The day's orders are replayed deterministically minute by minute up to "now" (the full day once closed). Each
minute: reveal that minute's orders and observations (courier ETAs/arrivals, pickup customers, incidents), admit
new orders through the ladder, rank the one queue (queue.py), reserve the kitchen (capacity.py, Savvy's
reservation logic), start what the plan says starts now, advance work by the (hidden) actual durations, hand off.
Every observation and decision becomes an idempotent ledger event (source "present", keys "present:...").

Arms on identical inputs: "gondola" (queue + ladder + pricing + rush agent; the only arm that writes the ledger),
"queue_only" (queue without admission control) and "fifo" (first in, first out, everything accepted).
All promises, couriers, distances, tasks, durations and incidents are synthetic (world.py).
"""
from __future__ import annotations

import copy
import math
import threading
from collections import OrderedDict
from datetime import datetime, timedelta

from . import admission as adm
from . import capacity as cap
from . import queue as qmod
from .queue import QOrder, QTask, make_task
from .settings import PresentSettings, load as load_settings
from .world import (CHANNELS, DELIVERY_APPS, MENU, STATION_NAMES, STATIONS, SYNTHETIC, World, hm, parse_hm,
                    u, weather as weather_at, world_for)

SOURCE = "present"


# ------------------------------------------------------------------ forecast arrivals (Future, else history)
_ARR_CACHE: dict = {}


def arrivals(w: World, minute: int) -> tuple[list[dict], str]:
    """Expected arrivals per 15-minute bin and channel from `minute` on: Future's nowcast when available
    (gondola.future.nowcast.arrivals), else the same-weekday historical profile. [{t, channel, p50, p90}]."""
    b = minute // 15
    # Outlook snapshots can expire mid-bin; never reuse an agent forecast after expiry.
    from ..future.outlook import active as active_outlook
    snapshot = active_outlook(w.date, datetime.fromisoformat(w.date) + timedelta(minutes=minute))
    key = (w.date, b, snapshot["run_id"] if snapshot else None)
    if key in _ARR_CACHE:
        return _ARR_CACHE[key]
    out, src = [], "history: same weekday, previous 4 weeks"
    try:
        from ..future.nowcast import arrivals as nowcast  # type: ignore
        d0 = datetime.fromisoformat(w.date)
        try:  # Future issues its own forecast.issued events; a replay must not
            rows = nowcast(w.date, d0 + timedelta(minutes=minute), issue=False)
        except TypeError:
            rows = nowcast(w.date, d0 + timedelta(minutes=minute))
        for r in rows or []:
            t = parse_hm(r["time"])
            ch = r.get("channel")
            p50, p90 = float(r.get("p50", 0) or 0), float(r.get("p90", r.get("p50", 0)) or 0)
            if ch == "in_store":
                out += [{"t": t, "channel": "dine_in", "p50": p50 * 0.6, "p90": p90 * 0.6},
                        {"t": t, "channel": "pickup", "p50": p50 * 0.4, "p90": p90 * 0.4}]
            elif ch in CHANNELS:
                out.append({"t": t, "channel": ch, "p50": p50, "p90": p90})
        if out:
            src = "future.nowcast"
    except Exception:
        out = []
    if not out:
        for (t, ch), v in w.profile["bins"].items():
            if t + 15 > minute:
                out.append({"t": t, "channel": ch, "p50": v, "p90": v * 1.3})
    if len(_ARR_CACHE) > 4000:
        _ARR_CACHE.clear()
        _RUNOUT.clear()
    _ARR_CACHE[key] = (out, src)
    return out, src


_RUNOUT: dict = {}


def _stock(d: str, minute: int, sold: dict[str, int]) -> dict[str, int]:
    """Stock for Savvy's guard: chashu items from Future's runout (gondola.future.items.runout, cached per 15 min)
    when available, else a declared 40 per item less a quarter of today's sales of that item (synthetic)."""
    base = {k: max(0, 40 - sold.get(k, 0) // 4) for k in ("Tonkotsu", "Karaage", "Gyoza", "Chashu Don")}
    from ..future.outlook import active as active_outlook
    snapshot = active_outlook(d, datetime.fromisoformat(d) + timedelta(minutes=minute))
    key = (d, minute // 15, snapshot["run_id"] if snapshot else None)
    if key not in _RUNOUT:
        rows = None
        try:
            from ..future.items import runout  # type: ignore
            rows = runout(d, datetime.fromisoformat(d) + timedelta(minutes=minute))
        except Exception:
            rows = None
        if len(_RUNOUT) > 2000:
            _RUNOUT.clear()
        _RUNOUT[key] = rows
    for r in _RUNOUT[key] or []:
        if r.get("key") == "chashu" and r.get("believed_left") is not None:
            left = max(0.0, float(r["believed_left"]))
            base["Tonkotsu"], base["Chashu Don"] = int(left), int(left / 1.5)   # portions per item (menu table)
    return base


# ------------------------------------------------------------------ the engine
class Engine:
    def __init__(self, d: str, settings: PresentSettings | None = None, mode: str = "gondola",
                 overrides: list[dict] | None = None, agent: bool = True):
        if mode not in ("gondola", "queue_only", "fifo"):
            raise ValueError("unknown mode")
        self.s = settings or load_settings()
        self.w = world_for(d, self.s)
        self.d, self.mode = d, mode
        self.by_minute = self.w.by_minute()
        first = min(self.by_minute) if self.by_minute else self.w.open_min
        self.start = min(self.w.open_min, first)
        self.t = self.start
        self.orders: dict[str, QOrder] = {}
        self.meta: dict[str, dict] = {}
        self.declined: list[dict] = []
        self.speeds = {s: 1.0 for s in STATIONS}
        self.ladder = adm.LadderState(0, self.start)
        self.channels = adm.channel_template()
        self.holds: list[dict] = []          # agent/manager actions with TTL
        self.overrides: dict[int, list[dict]] = {}
        for o in overrides or []:
            self.overrides.setdefault(int(o["minute"]), []).append(o)
        self.events: list[dict] = []
        self.actions: list[dict] = []
        self.offer: dict | None = None
        self.offer_blocked_until = -1
        self.spent = 0
        self.sold: dict[str, int] = {}
        self.prev_starts: dict[str, int] = {}
        self.next_up: set = set()
        self.churn = 0
        self.plan: list[dict] = []
        self.finish: dict[str, int] = {}
        self.ranked: list[dict] = []
        self.head: cap.Headroom | None = None
        self.arr_src = ""
        self.agent_enabled = agent and mode == "gondola"
        self.agent_last = -10 ** 6
        self.agent_runs: list[dict] = []
        self.eta_log: list[tuple[int, float]] = []
        self.incident_log: list[dict] = []
        self.seq = 0
        self.est = dict(self.w.durations)     # in-day learned planning minutes per item (Savvy's EMA, alpha 0.25)
        self.samples: dict[str, int] = {}

    # -------------------------------------------------------------- helpers
    def ts(self, minute: float) -> str:
        dt = datetime.fromisoformat(self.d) + timedelta(minutes=minute)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    def emit(self, type_: str, minute: float, payload: dict, key: str):
        if self.mode != "gondola":
            return
        payload = {**payload, "synthetic": True}
        self.events.append({"type": type_, "date": self.d, "ts": self.ts(minute), "source": SOURCE,
                            "key": f"present:{self.d}:{key}", "payload": payload})

    def cooks_at(self, m: int) -> int:
        return self.w.cooks_at(m)

    @property
    def closed(self) -> bool:
        """Past closing, no more orders to come, and every accepted order handed off."""
        if self.t < self.w.close_min or (self.by_minute and self.t <= max(self.by_minute)):
            return False
        return all(m["handed"] is not None for m in self.meta.values())

    def weather(self, m: int | None = None) -> dict:
        return weather_at(self.d, self.t if m is None else m)

    # -------------------------------------------------------------- admission
    def _admit(self, wo, minute: int):
        items = list(wo.items)
        if self.mode == "gondola":
            decision, reason, extra = adm.decide(self.channels, wo.channel, items, minute)
        else:
            decision, reason, extra = "accepted", "accepted (no admission control in this arm)", 0
        base = {"order_id": wo.order_id, "channel": wo.channel, "items": items, "subtotal": wo.subtotal,
                "promise": hm(wo.promise), "fulfillment": wo.fulfillment, "customer_distance_km": wo.customer_distance_km,
                "courier_eta": None}
        self.emit("order.received", wo.created, base, f"{wo.order_id}:received")
        level = adm.LEVELS[self.ladder.level]
        if decision == "declined":
            self.declined.append({"order_id": wo.order_id, "channel": wo.channel, "minute": minute,
                                  "subtotal": wo.subtotal, "reason": reason})
            self.emit("order.declined", wo.created, {"order_id": wo.order_id, "reason": reason, "ladder_level": level},
                      f"{wo.order_id}:declined")
            return
        promise = wo.promise + extra
        o = QOrder(wo.order_id, wo.channel, wo.fulfillment, wo.created, float(promise), items=items,
                   customer_distance_km=wo.customer_distance_km if wo.fulfillment == "delivery" else None)
        truth = {}
        for t in wo.tasks:
            o.tasks.append(make_task(t["task_id"], t["item"], t["station"], float(self.est.get(t["item"], t["nominal"]))))
            truth[t["task_id"]] = t["truth"]
        o.pack = make_task(wo.pack["task_id"], None, "packing", float(wo.pack["nominal"]))
        truth[wo.pack["task_id"]] = wo.pack["truth"]
        planned = {t.task_id: t.remaining for t in o.tasks + [o.pack]}
        meta = {"world": wo, "promise_orig": wo.promise, "extra": extra, "truth": truth, "progress": {},
                "decision": decision, "arrival": None, "handed": None, "sched": [], "planned": planned}
        if wo.fulfillment == "delivery":
            c = wo.courier
            arrival = max(promise + c["arrival_off"], c["assign_at"] + c["travel_min"])
            mid = int((c["assign_at"] + arrival) / 2)
            e0, e1 = c["eta_noise"]
            meta["arrival"] = arrival
            meta["sched"] = [(c["assign_at"], "eta", arrival + e0, c["distance_km"]),
                             (max(c["assign_at"] + 1, mid), "eta", arrival + e1,
                              round(c["distance_km"] * max(0.0, (arrival - mid) / max(1.0, arrival - c["assign_at"])), 1)),
                             (int(math.floor(arrival)), "arrived", arrival, 0.0)]
        elif wo.fulfillment == "pickup":
            meta["arrival"] = max(wo.created + 3, promise + wo.customer_arrival_off)
            meta["sched"] = [(int(math.floor(meta["arrival"])), "customer", meta["arrival"], None)]
        else:
            o.customer_present = True
            meta["arrival"] = float(promise)      # the seated guest expects food at the ticket target
        self.orders[o.order_id] = o
        self.meta[o.order_id] = meta
        for it in items:
            self.sold[it] = self.sold.get(it, 0) + 1
        payload = {"order_id": wo.order_id, "reason": reason, "ladder_level": level}
        if decision == "quoted":
            payload["quoted_ready"] = hm(promise)
            self.emit("order.quoted", wo.created, payload, f"{wo.order_id}:quoted")
        self.emit("order.accepted", wo.created, {**payload, "promise": hm(promise)}, f"{wo.order_id}:accepted")
        if wo.fulfillment == "dine_in":
            self.emit("customer.arrived", wo.created, {"order_id": wo.order_id, "fulfillment": "dine_in"},
                      f"{wo.order_id}:customer")

    # -------------------------------------------------------------- observations
    def _observe(self, m: int):
        for st in STATIONS:
            sp = self.w.speed(st, m)
            if sp != self.speeds[st]:
                inc = next((i for i in self.w.incidents if i["station"] == st and i["start"] == m), None)
                text = inc["text"] if inc else f"{STATION_NAMES[st]} back to full speed"
                self.incident_log.append({"minute": m, "station": st, "speed": sp, "text": text, "start": bool(inc)})
                self.emit("incident.started" if inc else "incident.ended", m,
                          {"kind": inc["kind"] if inc else "recovered", "station": st, "speed": sp, "text": text},
                          f"station:{st}:{m}")
            self.speeds[st] = sp
        for oid, o in self.orders.items():
            meta = self.meta[oid]
            for ev in meta["sched"]:
                if ev[0] != m:
                    continue
                if ev[1] == "eta":
                    prev = o.courier_eta
                    o.courier_eta, o.courier_distance_km = float(ev[2]), ev[3]
                    if prev is not None:
                        self.eta_log.append((m, o.courier_eta - prev))
                    self.emit("courier.eta_updated", m, {"order_id": oid, "channel": o.channel, "eta": hm(ev[2]),
                                                         "distance_km": ev[3]}, f"{oid}:eta:{m}")
                elif ev[1] == "arrived":
                    o.courier_arrived, o.courier_eta, o.courier_distance_km = True, float(ev[2]), 0.0
                    self.emit("courier.arrived", ev[2], {"order_id": oid, "channel": o.channel, "eta": hm(ev[2]),
                                                         "distance_km": 0.0}, f"{oid}:courier")
                elif ev[1] == "customer":
                    o.customer_present = True
                    self.emit("customer.arrived", ev[2], {"order_id": oid, "fulfillment": "pickup"}, f"{oid}:customer")

    # -------------------------------------------------------------- ladder, holds, pricing
    def action(self, m: int, payload: dict, by: str = "controller"):
        self.seq += 1
        h = self.head
        p = {"ladder_level": adm.LEVELS[self.ladder.level], "headroom_pct": round(h.pct, 1) if h else None,
             "by": by, **payload}
        self.actions.append({"minute": m, "time": hm(m), **p})
        self.emit("action.applied", m, p, f"action:{m}:{self.seq}")

    def _predicted_delay(self) -> float:
        late = sorted(max(0, self.finish.get(oid, 0) - o.promise) for oid, o in self.orders.items()
                      if o.ready is None and o.fulfillment == "delivery")
        return float(late[int(0.75 * (len(late) - 1))]) if late else 0.0

    def _apply_level(self, m: int, old: int, new: int):
        h = self.head
        bind = h.binding if h else "fryer"
        reason = f"headroom {h.pct:.0f}% (binding: {bind}) -> {adm.LEVELS[new]}" if h else adm.LEVELS[new]
        self.action(m, {"action": "ladder", "value": adm.LEVELS[new], "from": adm.LEVELS[old], "reason": reason})
        # quote
        if new <= -1:
            extra = adm.quote_extra(self._predicted_delay(), h.pct if h else 0, self.s.kitchen.window_min)
            for app in DELIVERY_APPS:
                if self.channels[app]["quoted_extra_min"] != extra:
                    self.channels[app]["quoted_extra_min"] = extra
                    self.action(m, {"action": "quote", "channel": app, "value": extra,
                                    "reason": f"quote +{extra} min: predicted delay at headroom {h.pct:.0f}%"})
        # pause slow items on the binding station, Grubhub first
        if new <= -2:
            items = adm.slow_items(bind if bind in ("noodles", "fryer", "assembly") else "fryer", self.w.durations)
            for app in adm.PAUSE_ORDER:
                ch = self.channels[app]
                add = [i for i in items if i not in ch["paused_items"]]
                if add:
                    ch["paused_items"] += add
                    for i in add:
                        ch["effective"]["pause:" + i] = m + adm.PROPAGATION[app]
                    self.action(m, {"action": "pause_item", "channel": app, "item": ", ".join(add),
                                    "reason": f"{bind} is the bottleneck: pause slow items ({app} pause takes "
                                              f"~{adm.PROPAGATION[app]} min to propagate)"})
        # busy mode: cheapest-contribution app first; stop promotions
        if new <= -3:
            self._busy_next(m, "headroom below the busy threshold")
        if new <= -1 and self.offer:
            self._stop_offer(m, "ladder tightened: no promotions while quoting/pausing")
        # relax (actions the Rush agent or a manager applied stay until their hold expires)
        held = {(hd["channel"], hd["action"]) for hd in self.holds if m < hd["until"]}
        if new >= 0:
            for app in DELIVERY_APPS:
                if any(c == app for c, _ in held):
                    continue
                ch = self.channels[app]
                if ch["quoted_extra_min"] or ch["paused_items"] or ch["busy"]:
                    ch.update({"quoted_extra_min": 0, "paused_items": [], "busy": False, "effective": {}})
                    self.action(m, {"action": "resume", "channel": app, "reason": f"headroom back to {h.pct:.0f}%"})
        elif new == -1:
            for app in DELIVERY_APPS:
                if (app, "pause_item") in held or (app, "busy") in held:
                    continue
                ch = self.channels[app]
                if ch["paused_items"] or ch["busy"]:
                    ch.update({"paused_items": [], "busy": False, "effective": {}})
                    self.action(m, {"action": "resume", "channel": app, "value": "quote only",
                                    "reason": f"headroom recovered to {h.pct:.0f}%: keep quoting, unpause"})
        elif new == -2:
            for app in DELIVERY_APPS:
                ch = self.channels[app]
                if ch["busy"]:
                    ch["busy"] = False
                    ch["effective"].pop("busy", None)
                    self.action(m, {"action": "resume", "channel": app, "value": "busy off",
                                    "reason": f"headroom recovered to {h.pct:.0f}%"})

    def _busy_next(self, m: int, reason: str, by: str = "controller") -> str | None:
        for app in adm.cheapest_first(self.w.contribution):
            ch = self.channels[app]
            if not ch["busy"]:
                ch["busy"] = True
                ch["effective"]["busy"] = m + adm.PROPAGATION[app]
                self.action(m, {"action": "busy", "channel": app,
                                "reason": f"{reason}; {app} keeps the least per order "
                                          f"({self.w.contribution.get(app, 0):.0%} of subtotal)"}, by)
                return app
        return None

    def _stop_offer(self, m: int, reason: str, by: str = "controller"):
        if self.offer:
            self.action(m, {"action": "offer_paused", "channel": "pickup", "item": self.offer["item_name"],
                            "reason": reason}, by)
            self.offer = None

    def _pricing(self, m: int):
        """Connected control: Savvy's offer guard on the same reservations, only when the ladder says promote."""
        if self.ladder.level < 1 or m < self.offer_blocked_until:
            if self.offer and (self.ladder.level < 1 or m < self.offer_blocked_until):
                self._stop_offer(m, "headroom no longer above the promote threshold")
            return
        if (m - self.start) % self.s.pricing.every_min:
            return
        k = self.kitchen(m)
        checks = [cap.guard_offer(k, key, self.s.pricing.discount_cents, self.s.kitchen.slots) for key in cap.RUSH_TO_ITEM]
        allowed = [c for c in checks if c["allowed"]]
        best = max(allowed, key=lambda c: (c["score"], c["item"]), default=None)
        if best is None:
            self._stop_offer(m, "no approved item passes the guard")
            return
        if self.offer and self.offer["item"] == best["item"]:
            return
        self.offer = {"item": best["item"], "item_name": best["item_name"], "discount_cents": best["discount_cents"],
                      "since": m, "evidence": {k: best[k] for k in ("station", "station_load", "contribution_cents",
                                                                    "predicted_ready_minute", "reason")}}
        self.action(m, {"action": "offer", "channel": "pickup", "item": best["item_name"], "value": best["discount_cents"],
                        "reason": f"promote: {best['station']} has room ({best['station_load']:.0%} load); "
                                  f"{best['reason']} (simulated first-party offer; demand response not modeled)"})

    def kitchen(self, m: int):
        prio = [r["order_id"] for r in self.ranked] or list(self.orders)
        return cap.present_kitchen(list(self.orders.values()), prio, m, self.speeds, self.s.kitchen.slots, self.cooks_at,
                                   self.s.pricing.budget_cents, self.spent, self.s.pricing.discount_cents,
                                   _stock(self.d, m, self.sold))

    # -------------------------------------------------------------- holds (agent / manager actions with TTL)
    def apply_action(self, m: int, a: dict, by: str) -> dict:
        """Apply a bounded action now. Kinds: quote, pause_item, busy, resume, pause_offer. Delivery apps only;
        never dine-in or pickup. Returns {status, reason}."""
        kind, app = a.get("action"), a.get("channel")
        if app in ("delivery", "all") and kind in ("quote", "pause_item", "busy", "resume"):
            res = [self.apply_action(m, {**a, "channel": x}, by) for x in DELIVERY_APPS]
            ok = [r for r in res if r["status"] == "applied"]
            return ok[0] if ok else res[0]
        ttl = int(a.get("ttl_min") or self.s.agent.action_ttl_min)
        if kind == "offer":
            key = a.get("item")
            if self.ladder.level < 1 or key not in cap.RUSH_TO_ITEM:
                return {"status": "rejected", "reason": "offers only at promote, approved items only"}
            check = cap.guard_offer(self.kitchen(m), key, int(a.get("value") or 0), self.s.kitchen.slots)
            if not check["allowed"]:
                return {"status": "rejected", "reason": "guard: " + check["reason"]}
            self.offer = {"item": key, "item_name": check["item_name"], "discount_cents": check["discount_cents"],
                          "since": m, "evidence": {k: check[k] for k in ("station", "station_load", "reason")}}
            self.action(m, {"action": "offer", "channel": "pickup", "item": check["item_name"],
                            "value": check["discount_cents"], "reason": a.get("reason") or check["reason"]}, by)
            return {"status": "applied", "reason": check["reason"]}
        if kind in ("quote", "pause_item", "busy", "resume") and app not in DELIVERY_APPS:
            return {"status": "rejected", "reason": "only delivery apps can be throttled; never dine-in or pickup"}
        ch = self.channels.get(app) if app else None
        if kind == "quote":
            v = int(a.get("value") or 5)
            if not 5 <= v <= 20:
                return {"status": "rejected", "reason": "quote must be 5-20 minutes"}
            ch["quoted_extra_min"] = max(ch["quoted_extra_min"], v)
        elif kind == "pause_item":
            items = a.get("items") or [i.strip() for i in str(a.get("item") or "").split(",") if i.strip()]
            items = [i for i in items if i in MENU and MENU[i]["station"]]
            if not items:
                return {"status": "rejected", "reason": "unknown or non-kitchen item"}
            for i in items:
                if i not in ch["paused_items"]:
                    ch["paused_items"].append(i)
                    ch["effective"]["pause:" + i] = m + adm.PROPAGATION[app]
            a = {**a, "item": ", ".join(items)}
        elif kind == "busy":
            ch["busy"] = True
            ch["effective"]["busy"] = m + adm.PROPAGATION[app]
        elif kind == "resume":
            ch.update({"quoted_extra_min": 0, "paused_items": [], "busy": False, "effective": {}})
        elif kind == "pause_offer":
            self.offer_blocked_until = m + ttl
            self._stop_offer(m, a.get("reason") or "guard conflict", by)
            return {"status": "applied", "reason": "offers paused"}
        elif kind == "none":
            return {"status": "applied", "reason": "no action"}
        else:
            return {"status": "rejected", "reason": f"action '{kind}' is not on the ladder"}
        if kind != "resume":
            self.holds.append({"until": m + ttl, "action": kind, "channel": app})
        self.action(m, {k: v for k, v in {"action": kind, "channel": app, "item": a.get("item"), "value": a.get("value"),
                                          "reason": a.get("reason") or "", "ttl_min": ttl}.items() if v is not None}, by)
        return {"status": "applied", "reason": a.get("reason") or kind}

    def _expire_holds(self, m: int):
        keep = []
        for hld in self.holds:
            if m < hld["until"]:
                keep.append(hld)
                continue
            # an expired hold hands back to the ladder: reapply the ladder's own level state
            app = hld["channel"]
            if app in self.channels and self.ladder.level >= -1 and hld["action"] in ("pause_item", "busy"):
                ch = self.channels[app]
                if ch["paused_items"] or ch["busy"]:
                    ch.update({"paused_items": [], "busy": False})
                    self.action(m, {"action": "resume", "channel": app, "reason": "agent hold expired; ladder decides"})
            if app in self.channels and self.ladder.level >= 0 and hld["action"] == "quote":
                if self.channels[app]["quoted_extra_min"]:
                    self.channels[app]["quoted_extra_min"] = 0
                    self.action(m, {"action": "resume", "channel": app, "reason": "agent quote expired; ladder decides"})
        self.holds = keep

    # -------------------------------------------------------------- agent triggers
    def triggers(self, m: int) -> list[str]:
        a = self.s.agent
        out = []
        h = self.head
        if h and min(h.pct, h.ahead_pct) < a.trigger_headroom_pct:
            out.append(f"headroom predicted {min(h.pct, h.ahead_pct):.0f}% within {a.trigger_lookahead_min} min")
        if any(i["minute"] == m and i["start"] for i in self.incident_log):
            out.append("incident: " + next(i["text"] for i in self.incident_log if i["minute"] == m and i["start"]))
        late = [d for (t, d) in self.eta_log if m - 10 <= t <= m and d >= a.courier_delay_min]
        if len(late) >= a.courier_delay_cluster:
            out.append(f"courier delays: {len(late)} ETAs moved {a.courier_delay_min:.0f}+ min later in 10 min")
        if self.offer and h:
            st = MENU[self.offer["item_name"]]["station"]
            if st == h.binding and h.by_resource[st]["pct"] < 0:
                out.append(f"guard conflict: promoting {self.offer['item_name']} on the bottleneck station {st}")
        return out

    def _agent(self, m: int):
        trig = self.triggers(m)
        if not trig:
            return
        incident = any(t.startswith("incident") for t in trig)
        if m - self.agent_last < self.s.agent.min_gap_min and not incident:
            return
        from .agent import offline_decide
        self.agent_last = m
        decision = offline_decide(self, m, trig)
        res = None
        if decision.get("action") and decision["action"].get("action") != "none":
            res = self.apply_action(m, decision["action"], "rush-agent")
        self.agent_runs.append({"minute": m, "time": hm(m), "triggers": trig, "decision": decision.get("summary"),
                                "action": decision.get("action"), "result": res, "candidates": decision.get("candidates")})

    # -------------------------------------------------------------- one minute
    def rank_and_plan(self, m: int):
        orders = list(self.orders.values())
        wx = self.weather(m)
        if self.mode == "fifo":
            prio = qmod.fifo_rank(orders)
            ranked = []
            for i, oid in enumerate(prio):
                s = qmod.score(self.orders[oid], m, self.speeds, wx, self.s)
                ranked.append(dict(s, rank=i + 1, status=self.orders[oid].status, batch_group=None))
            jit = False
        else:
            ranked = qmod.rank(orders, m, self.speeds, wx, self.s, self.next_up)
            prio = [r["order_id"] for r in ranked]
            jit = self.head is None or self.head.pct >= self.s.kitchen.jit_min_headroom_pct
        holds = {r["order_id"]: r["hold_tolerance"] for r in ranked} if jit else None
        plan, finish = cap.schedule(orders, prio, m, self.speeds, self.s.kitchen.slots, self.cooks_at, jit=jit, hold=holds,
                                    buffer=self.buffer(m, wx))
        return ranked, plan, finish

    def buffer(self, m: int, wx: dict | None = None) -> float:
        """Uncertainty buffer for just-in-time starts: base, +1 in rain/snow, +1 while a station is slowed."""
        wx = wx or self.weather(m)
        return self.s.kitchen.safety_buffer_min + (1.0 if wx.get("rain") or wx.get("snow") else 0.0) + \
            (1.0 if any(v < 1.0 for v in self.speeds.values()) else 0.0)

    def step(self):
        m = self.t
        self._observe(m)
        for wo in self.by_minute.get(m, []):
            self._admit(wo, m)
        # headroom (needed by ladder, agent and the state view)
        arr, self.arr_src = arrivals(self.w, m)
        k = self.s.kitchen
        self.head = cap.headroom(list(self.orders.values()), m, self.speeds, k.slots, self.cooks_at, arr,
                                 self.w.profile["work_per_order"], k.window_min, k.forecast_lead_min,
                                 self.s.agent.trigger_lookahead_min)
        self.ranked, self.plan, self.finish = self.rank_and_plan(m)
        if self.mode == "gondola":
            self._expire_holds(m)
            for o in self.overrides.get(m, []):
                self.apply_action(m, o["action"], o.get("by", "manager"))
            ch = self.ladder.update(m, self.head.pct, self.s.ladder)
            if ch:
                self._apply_level(m, *ch)
            elif self.ladder.level == -3 and self.head.pct < self.s.ladder.busy_below and \
                    (m - self.ladder.since) % max(5, self.s.ladder.hysteresis_min) == 0 and m != self.ladder.since:
                self._busy_next(m, "still below the busy threshold")
            self._pricing(m)
            if self.agent_enabled:
                self._agent(m)
            if self.actions and self.actions[-1]["minute"] == m:
                self.ranked, self.plan, self.finish = self.rank_and_plan(m)
        # churn: planned starts of unstarted work moving by more than a minute
        starts = {r["task_id"]: r["start"] for r in self.plan if not r["frozen"]}
        self.churn += sum(1 for tid, s in starts.items() if tid in self.prev_starts and abs(s - self.prev_starts[tid]) > 1)
        self.prev_starts = starts
        self.next_up = {r["order_id"] for r in self.plan if not r["frozen"] and m < r["start"] <= m + 2}
        # start what the plan starts now
        tasks = {t.task_id: (o, t) for o in self.orders.values() for t in o.tasks + ([o.pack] if o.pack else [])}
        for r in self.plan:
            if r["frozen"] or r["start"] != m:
                continue
            o, t = tasks[r["task_id"]]
            if t.started:
                continue
            t.started, t.start = True, m
            self.emit("task.started", m, {"order_id": o.order_id, "task_id": t.task_id, "item": t.item,
                                          "station": t.station, "planned_min": round(t.remaining, 2)},
                      f"{t.task_id}:started")
        # advance work by the actual (hidden) durations
        for o in self.orders.values():
            if o.ready is not None:
                continue
            meta = self.meta[o.order_id]
            for t in o.tasks + ([o.pack] if o.pack else []):
                if not t.started or t.done:
                    continue
                if t.station == "packing" and any(not c.done for c in o.tasks):
                    continue
                sp = self.speeds[t.station]
                prog = meta["progress"].get(t.task_id, 0.0) + sp
                meta["progress"][t.task_id] = prog
                nominal = meta["planned"][t.task_id]
                t.remaining = max(0.5, nominal - prog)
                if prog + 1e-9 >= meta["truth"][t.task_id]:
                    t.done, t.remaining = True, 0.0
                    if t.item:  # learn only from an observed completion (work done at speed 1.0), as Savvy does
                        self.samples[t.item] = self.samples.get(t.item, 0) + 1
                        self.est[t.item] = round(0.75 * self.est.get(t.item, nominal) + 0.25 * prog, 3)
                    self.emit("task.finished", m + 1, {"order_id": o.order_id, "task_id": t.task_id, "item": t.item,
                                                       "station": t.station, "planned_min": round(nominal, 2),
                                                       "actual_min": float(m + 1 - t.start)}, f"{t.task_id}:finished")
            if o.pack and o.pack.done and o.ready is None:
                o.ready = float(m + 1)
        # hand-offs: food ready and the courier/customer/guest is there
        for o in self.orders.values():
            meta = self.meta[o.order_id]
            if o.ready is None or meta["handed"] is not None:
                continue
            arr = meta["arrival"]
            if o.fulfillment == "dine_in":
                handed = o.ready
            elif arr is not None and arr <= m + 1:
                handed = max(o.ready, arr)
            else:
                continue
            meta["handed"] = handed
            wait = max(0.0, o.ready - arr)
            hold = 0.0 if o.fulfillment == "dine_in" else max(0.0, arr - o.ready)
            late = max(0.0, o.ready - o.promise)
            meta.update(wait=wait, hold=hold, late=late)
            self.emit("order.handed_off", handed, {"order_id": o.order_id, "channel": o.channel, "ready": hm(o.ready),
                                                   "handed": hm(handed), "wait_min": round(wait, 1), "hold_min": round(hold, 1),
                                                   "late_min": round(late, 1), "promise": hm(o.promise),
                                                   "fulfillment": o.fulfillment}, f"{o.order_id}:handed")
        self.t += 1

    def run_until(self, minute: int):
        end = min(minute, self.w.close_min + 300)
        while self.t < end:
            self.step()
            if self.closed:
                break

    def run_day(self):
        self.run_until(self.w.close_min + 300)

    # -------------------------------------------------------------- views
    def metrics(self) -> dict:
        done = [(o, self.meta[o.order_id]) for o in self.orders.values() if self.meta[o.order_id].get("handed") is not None]
        waits = [m["wait"] for _, m in done]
        holds = [m["hold"] for _, m in done]
        met = sum(1 for o, m in done if o.ready <= o.promise)
        met_orig = sum(1 for o, m in done if o.ready <= m["promise_orig"])
        by = {}
        for ch in CHANNELS:
            rows = [(o, m) for o, m in done if o.channel == ch]
            by[ch] = {"orders": len(rows), "promises_met": sum(1 for o, m in rows if o.ready <= o.promise),
                      "avg_wait": round(sum(m["wait"] for _, m in rows) / len(rows), 2) if rows else 0.0,
                      "worst_wait": round(max([m["wait"] for _, m in rows] or [0]), 1),
                      "declined": sum(1 for x in self.declined if x["channel"] == ch)}
        n = len(done)
        return {"orders": n, "accepted": len(self.orders), "in_progress": len(self.orders) - n,
                "promises_met": met, "promises_total": n, "promises_met_pct": round(100 * met / n, 1) if n else None,
                "promises_met_original": met_orig,
                "avg_wait": round(sum(waits) / n, 2) if n else 0.0, "worst_wait": round(max(waits or [0]), 1),
                "avg_hold": round(sum(holds) / n, 2) if n else 0.0, "hold": round(sum(holds), 1),
                "late_orders": n - met, "late_minutes": round(sum(m["late"] for _, m in done), 1),
                "worst_late": round(max([m["late"] for _, m in done] or [0]), 1),
                "declined": len(self.declined), "declined_sales": round(sum(x["subtotal"] for x in self.declined), 2),
                "quoted": sum(1 for mm in self.meta.values() if mm["extra"]),
                "schedule_changes": self.churn, "by_channel": by}

    def view(self) -> dict:
        """The decision boundary at the start of minute self.t: queue, stations, channels."""
        m = self.t
        if not self.orders:
            return {"queue": [], "stations": [self._station(s, [], m) for s in STATIONS]}
        ranked, plan, finish = self.rank_and_plan(m)
        rows_by = {}
        for r in plan:
            rows_by.setdefault(r["order_id"], []).append(r)
        queue = []
        for r in ranked:
            o = self.orders[r["order_id"]]
            meta = self.meta[o.order_id]
            unfinished = [t for t in o.tasks if not t.done]
            station = max(unfinished, key=lambda t: t.remaining).station if unfinished else "packing"
            starts = [x["start"] for x in rows_by.get(o.order_id, []) if not x["frozen"]]
            queue.append({"rank": r["rank"], "order_id": o.order_id, "channel": o.channel, "items": o.items,
                          "fulfillment": o.fulfillment, "created": hm(o.created), "promise": hm(o.promise),
                          "quoted_extra_min": meta["extra"], "courier_eta": hm(o.courier_eta),
                          "courier_distance_km": o.courier_distance_km, "courier_arrived": o.courier_arrived,
                          "customer_distance_km": o.customer_distance_km, "customer_present": o.customer_present,
                          "due": hm(r["due"]), "due_source": r["due_source"], "latest_start": hm(r["latest_start"]),
                          "slack_min": r["slack_min"], "station": station, "status": o.status,
                          "planned_start": hm(min(starts)) if starts else None,
                          "planned_ready": hm(finish.get(o.order_id)),
                          "predicted_late_min": max(0, finish.get(o.order_id, m) - int(o.promise)),
                          "factors": r["factors"], "priority": r["priority"], "batch_group": r.get("batch_group"),
                          "frozen": o.status != "queued", "reason": r["reason"]})
        # ready orders waiting for pickup are listed after the cooking queue
        for o in self.orders.values():
            meta = self.meta[o.order_id]
            if o.ready is not None and meta.get("handed") is None:
                queue.append({"rank": len(queue) + 1, "order_id": o.order_id, "channel": o.channel, "items": o.items,
                              "fulfillment": o.fulfillment, "created": hm(o.created), "promise": hm(o.promise),
                              "quoted_extra_min": meta["extra"], "courier_eta": hm(o.courier_eta),
                              "courier_distance_km": o.courier_distance_km, "courier_arrived": o.courier_arrived,
                              "customer_distance_km": o.customer_distance_km, "customer_present": o.customer_present,
                              "due": hm(o.promise), "due_source": "promise", "latest_start": None, "slack_min": None,
                              "station": "pass", "status": "ready", "planned_start": None, "planned_ready": hm(o.ready),
                              "predicted_late_min": max(0, int(o.ready - o.promise)),
                              "factors": {k: 0.0 for k in qmod.FACTORS}, "priority": None, "batch_group": None,
                              "frozen": True, "reason": f"ready {hm(o.ready)}, waiting for the "
                                                        f"{'courier' if o.fulfillment == 'delivery' else 'customer'}"})
        stations = [self._station(s, [r for r in plan if r["station"] == s], m) for s in STATIONS]
        return {"queue": queue, "stations": stations}

    def _station(self, s: str, rows: list[dict], m: int) -> dict:
        window = [r for r in rows if r["start"] < m + 60]
        return {"key": s, "name": STATION_NAMES[s], "speed": self.speeds.get(s, 1.0), "slots": self.s.kitchen.slots.get(s, 1),
                "busy_until": hm(max([r["end"] for r in rows] or [m])),
                "load_30m": round(sum(max(0, min(m + 30, r["end"]) - max(m, r["start"])) for r in rows)
                                  / (30 * max(1, self.s.kitchen.slots.get(s, 1))), 2),
                "tasks": [{"order_id": r["order_id"], "item": r["item"], "start": hm(r["start"]), "end": hm(r["end"]),
                           "frozen": r["frozen"]} for r in sorted(window, key=lambda r: (r["start"], r["task_id"]))]}

    def channel_view(self) -> dict:
        out = {}
        for app in DELIVERY_APPS:
            ch = self.channels[app]
            state = "busy" if ch["busy"] else "paused_items" if ch["paused_items"] else "quoted" if ch["quoted_extra_min"] else "open"
            out[app] = {"state": state, "quoted_extra_min": ch["quoted_extra_min"], "paused_items": list(ch["paused_items"])}
        out["pickup"] = {"state": "open", "quoted_extra_min": 0, "paused_items": [], "offer": self.offer and
                         {k: self.offer[k] for k in ("item_name", "discount_cents", "since")}}
        out["dine_in"] = {"state": "open", "quoted_extra_min": 0, "paused_items": []}
        return out

    # -------------------------------------------------------------- copies for simulation
    def fork(self) -> "Engine":
        memo = {id(self.w): self.w, id(self.s): self.s, id(self.by_minute): self.by_minute}
        return copy.deepcopy(self, memo)


# ------------------------------------------------------------------ projection (simulate an action, no future truth)
def project(e: Engine, action: dict | None = None, horizon: int | None = None) -> dict:
    """Project the next `horizon` minutes with a candidate action using only what the controller may know: accepted
    work at planned durations, current courier ETAs, and forecast arrivals (Future's nowcast or the weekday profile)
    as pseudo-orders with recent baskets. Returns predicted late orders, late minutes, lost orders and headroom."""
    m = e.t
    horizon = horizon or e.s.kitchen.window_min
    arr, _ = arrivals(e.w, m)
    action = action or {"action": "none"}
    kind, app = action.get("action"), action.get("channel")
    apps = [app] if app in DELIVERY_APPS else (DELIVERY_APPS if app in (None, "all", "delivery") else [])
    paused = action.get("items") or ([i.strip() for i in str(action.get("item")).split(",")] if action.get("item") else [])
    quote = int(action.get("value") or 0) if kind == "quote" else 0
    orders = [copy.deepcopy(o) for o in e.orders.values() if o.ready is None]
    pseudo, lost, quoted_min = [], 0, 0
    per_ch = cap.forecast_orders(arr, m, m + horizon)
    removed: dict[str, float] = {}
    for ch, n in sorted(per_ch.items()):
        pool = e.w.profile["pools"].get(ch) or [["Tonkotsu"]]
        k = int(round(n))
        dropped = 0
        for i in range(k):
            items = pool[int(u(e.d, m, ch, i) * len(pool))]
            t0 = m + (i + 0.5) * horizon / max(k, 1)
            if ch in apps and (kind == "busy" or (kind == "pause_item" and any(x in paused for x in items))):
                lost += 1
                dropped += 1
                continue
            ful = "delivery" if ch in DELIVERY_APPS else ch
            promise = t0 + (20 if ful == "delivery" else 17 if ful == "pickup" else e.s.kitchen.dine_in_target_min)
            if ful == "delivery" and ch in apps and quote:
                promise += quote
                quoted_min += quote
            q = QOrder(f"F{ch[:2]}{i}", ch, ful, t0, promise, items=list(items),
                       customer_present=(ful == "dine_in"))
            for j, it in enumerate(items):
                st = MENU.get(it, {}).get("station")
                if st:
                    q.tasks.append(make_task(f"{q.order_id}:{j}", it, st, float(e.w.durations.get(it, 4.0))))
            q.pack = make_task(f"{q.order_id}:pack", None, "packing", 2.0 if len(items) >= 4 else 1.0)
            pseudo.append(q)
        if k:
            removed[ch] = dropped / k
    allq = orders + pseudo
    wx = e.weather(m)
    ranked = qmod.rank(allq, m, e.speeds, wx, e.s)
    prio = [r["order_id"] for r in ranked]
    # pseudo-orders cannot start before they arrive: plan them in arrival order after current work at equal priority
    plan, finish = _schedule_with_release(allq, prio, m, e)
    late = [(o.order_id, finish.get(o.order_id, m) - o.promise) for o in allq if finish.get(o.order_id, m) > o.promise]
    k = e.s.kitchen
    head = cap.headroom(orders, m, e.speeds, k.slots, e.cooks_at, arr, e.w.profile["work_per_order"], k.window_min,
                        k.forecast_lead_min, e.s.agent.trigger_lookahead_min, removed)
    return {"late_orders": len(late), "late_minutes": round(sum(x for _, x in late), 1),
            "late_accepted": sum(1 for oid, _ in late if oid in e.orders), "lost_orders": lost, "quoted_minutes": quoted_min,
            "headroom_pct": round(head.pct, 1), "ahead_pct": round(head.ahead_pct, 1), "pseudo_orders": len(pseudo)}


def _schedule_with_release(orders: list[QOrder], prio: list[str], m: int, e: Engine):
    """Schedule where an order's tasks never start before it is created (for forecast pseudo-orders)."""
    future = [o for o in orders if o.created > m]
    now = [o for o in orders if o.created <= m]
    if not future:
        return cap.schedule(orders, prio, m, e.speeds, e.s.kitchen.slots, e.cooks_at)
    # Delay pseudo-order work by inflating its hold-free release: reserve current work, then pseudo-orders in
    # arrival order, each starting no earlier than its arrival (first_fit from max(now, created)).
    g = cap.Grid(m, e.s.kitchen.slots, e.cooks_at)
    rows, finish = [], {}
    rows0, fin0 = cap.schedule(now, [p for p in prio if p in {o.order_id for o in now}], m, e.speeds, e.s.kitchen.slots, e.cooks_at)
    for r in rows0:
        g.reserve(r["station"], r["start"], r["end"] - r["start"],
                  0.0 if r["station"] == "packing" else MENU.get(r["item"] or "", {}).get("labour", 0.0))
    finish.update(fin0)
    for o in sorted(future, key=lambda o: o.created):
        t0 = int(math.ceil(o.created))
        end = t0
        for t in o.tasks:
            d = max(1, math.ceil(t.remaining / max(e.speeds.get(t.station, 1.0), 0.1)))
            s = g.first_fit(t.station, t0, d, t.labour)
            g.reserve(t.station, s, d, t.labour)
            end = max(end, s + d)
        pd = max(1, math.ceil(o.pack.remaining))
        s = g.first_fit("packing", end, pd, 0.0)
        g.reserve("packing", s, pd, 0.0)
        finish[o.order_id] = s + pd
    return rows0 + rows, finish


# ------------------------------------------------------------------ the service API (cached, incremental)
_LOCK = threading.RLock()
_ENGINES: dict[tuple, Engine] = {}
_CHECKPOINTS: dict[tuple, dict[int, Engine]] = {}
_STATES: "OrderedDict[tuple, dict]" = OrderedDict()
_FLUSHED: dict[tuple, int] = {}


def _clock(d: str, now: datetime | None) -> tuple[int, str]:
    """(minute to replay up to, phase) for business date d at `now` (gondola.now by default)."""
    from .. import now as clock
    from .world import DB, close_min
    if now is not None:
        biz = (now - timedelta(hours=4)).date().isoformat()
        if d < biz:
            return 10 ** 6, "closed"
        if d > biz:
            return 0, "before_open"
        m = now.hour * 60 + now.minute + (1440 if now.date().isoformat() != d else 0)
        return m, ("before_open" if m < 11 * 60 else "open" if m < close_min(d) else "closed")
    info = clock.info(DB)
    if d != info["today"]:
        return (10 ** 6, "closed") if d < info["today"] else (0, "before_open")
    if info["phase"] == "closed":
        return 10 ** 6, "closed"
    if info["phase"] == "before_open":
        return 0, "before_open"
    w = clock.wall()
    return w.hour * 60 + w.minute, "open"


def overrides_for(d: str) -> list[dict]:
    try:
        from .receipts import overrides
        return overrides(d)
    except Exception:
        return []


def engine(d: str, minute: int, settings: PresentSettings | None = None, mode: str = "gondola") -> Engine:
    """The engine for date d advanced to `minute` (cached; incremental; hourly checkpoints for earlier minutes)."""
    s = settings or load_settings()
    ov = overrides_for(d) if mode == "gondola" else []
    key = (d, s.digest(), mode, len(ov), str(ov[-1]["id"]) if ov else "")
    with _LOCK:
        cps = _CHECKPOINTS.setdefault(key, {})
        e = _ENGINES.get(key)
        if e is None or e.t > minute:
            best = max((t for t in cps if t <= minute), default=None)
            e = cps[best].fork() if best is not None else Engine(d, s, mode, ov)
        while e.t < minute and not e.closed and e.t < e.w.close_min + 300:
            e.step()
            if e.t % 60 == 0 and e.t not in cps:
                cps[e.t] = e.fork()
        cur = _ENGINES.get(key)
        if cur is None or e.t >= cur.t:
            _ENGINES[key] = e
        if len(_ENGINES) > 24:
            for k in list(_ENGINES)[:-24]:
                _ENGINES.pop(k, None)
                _CHECKPOINTS.pop(k, None)
        return e


def flush(e: Engine) -> int:
    """Write the gondola arm's events so far to the ledger. Every event of a processed minute has already happened
    (its timestamp is at or before the engine's minute), and keys make re-runs idempotent. Returns new rows."""
    if e.mode != "gondola":
        return 0
    k = id(e)
    start = _FLUSHED.get(k, 0)
    rows = e.events[start:]
    if not rows:
        return 0
    try:
        from ..ledger import ledger
        n = ledger().extend(rows)
    except Exception:
        return 0
    _FLUSHED[k] = start + len(rows)
    return n


def _phase_minute(d: str, now: datetime | None, at: str | None) -> tuple[int, str]:
    if at:
        m = parse_hm(at)
        lim, phase = _clock(d, now)
        if phase == "before_open" and now is None:
            from ..now import info
            from .world import DB
            clock = info(DB)
            if d == clock["today"]:
                lim = parse_hm(clock["now"])
        if m > lim:
            raise ValueError("cannot replay past the store clock (no reading data after now)")
        return m, "replay"
    return _clock(d, now)


def state(d: str, now: datetime | None = None, at: str | None = None, settings: PresentSettings | None = None,
          write: bool = True, compare: bool = False, after: int | None = None) -> dict:
    """GET /api/present/state: the service at `now` (or at a replay time `at` on a closed day)."""
    from .world import has_data
    s = settings or load_settings()
    minute, phase = _phase_minute(d, now, at)
    if not has_data(d):
        return {"date": d, "now": None, "phase": "no_data", "headroom_pct": None, "ladder": None, "queue": [],
                "stations": [], "channels": {}, "actions": [], "weather": None, "source_mode": "synthetic",
                "notes": ["no orders for this date in the store data"]}
    ckey = (d, minute, s.digest(), len(overrides_for(d)), compare, phase)
    with _LOCK:
        if after is None and ckey in _STATES:
            _STATES.move_to_end(ckey)
            return _STATES[ckey]
        e = engine(d, minute, s)
        if write and phase != "replay":
            flush(e)
        out = build_state(e, phase, minute)
        if after is not None:
            out["playback_actions"] = [a for a in e.actions if after <= a["minute"] < minute]
    if compare:
        out["compare"] = compare_at(d, minute, s)
    with _LOCK:
        if after is None:
            _STATES[ckey] = out
        while len(_STATES) > 512:
            _STATES.popitem(last=False)
    return out


def build_state(e: Engine, phase: str, minute: int) -> dict:
    v = e.view()
    h = e.head
    m = e.t
    active_inc = [i for i in e.w.incidents if i["start"] <= m < i["end"]]
    ladder = {"level": adm.LEVELS[e.ladder.level], "value": e.ladder.level, "name": adm.LEVELS[e.ladder.level].title(),
              "since": hm(e.ladder.since), "next_threshold": e.ladder.next_threshold(e.s.ladder),
              "pending": adm.LEVELS.get(e.ladder.pending) if e.ladder.pending is not None else None}
    counts = {"received": len(e.orders) + len(e.declined), "accepted": len(e.orders), "declined": len(e.declined),
              "quoted": sum(1 for mm in e.meta.values() if mm["extra"]), "in_kitchen": sum(1 for o in e.orders.values() if o.ready is None),
              "awaiting_pickup": sum(1 for o in e.orders.values() if o.ready is not None and e.meta[o.order_id]["handed"] is None),
              "handed_off": sum(1 for mm in e.meta.values() if mm["handed"] is not None)}
    return {"date": e.d, "now": hm(m), "phase": phase, "minute": m, "handoffs": handoffs(e.d, e.ts(m)),
            "headroom_pct": round(h.pct, 1) if h else None, "headroom": h.to_dict() if h else None,
            "ladder": ladder, "queue": v["queue"], "stations": v["stations"], "channels": e.channel_view(),
            "actions": e.actions[-12:], "agent_runs": e.agent_runs[-5:], "weather": e.weather(m),
            "incidents": active_inc, "cooks": e.cooks_at(m), "counts": counts, "metrics": e.metrics(),
            "forecast_source": e.arr_src, "source_mode": "synthetic", "notes": e.w.notes}


def handoffs(d: str, upto_ts: str | None = None) -> list[dict]:
    """Review's exceptions handed to Present (exception.raised with decision "present"), unresolved, up to now.
    Read from the ledger outside the deterministic replay; shown in state and given to the Rush agent."""
    try:
        from ..ledger import ledger
        led = ledger()
        raised = led.query(d, ["exception.raised"], end_ts=upto_ts)
        resolved = {ev.payload.get("id") for ev in led.query(d, ["exception.resolved"], end_ts=upto_ts)}
        return [{"id": ev.payload.get("id"), "title": ev.payload.get("title"), "note": ev.payload.get("note"),
                 "ts": ev.ts} for ev in raised
                if ev.payload.get("decision") == "present" and ev.payload.get("id") not in resolved]
    except Exception:
        return []


def compare_at(d: str, minute: int, settings: PresentSettings | None = None) -> dict:
    """Gondola vs FIFO (and the queue without admission control) on identical inputs, for the service so far."""
    s = settings or load_settings()
    out = {}
    for mode in ("fifo", "queue_only", "gondola"):
        e = engine(d, minute, s, mode)
        out[mode] = e.metrics()
    g = out["gondola"]
    return {"date": d, "upto": hm(min(minute, engine(d, minute, s).t)), "orders": g["accepted"] + g["declined"],
            "fifo": out["fifo"], "gondola": out["gondola"], "queue_only": out["queue_only"],
            "notes": ["Identical synthetic inputs (orders, couriers, actual durations, incidents) for every arm.",
                      "promises_met is against the promise each customer accepted (quoted orders: the longer quote); "
                      "promises_met_original uses the app's first quote.",
                      "Gondola may decline orders (paused items / busy mode): they are counted, not hidden.",
                      SYNTHETIC]}


def compare(d: str, now: datetime | None = None, settings: PresentSettings | None = None) -> dict:
    minute, _ = _clock(d, now)
    return compare_at(d, minute, settings)


def simulate(d: str, action: dict, now: datetime | None = None, at: str | None = None,
             settings: PresentSettings | None = None) -> dict:
    """POST /api/present/simulate: projected effect of a candidate action from the current state."""
    minute, _ = _phase_minute(d, now, at)
    e = engine(d, minute, settings)
    base = project(e, None)
    after = project(e, action)
    notes = ["Projection uses planned durations, current courier ETAs and forecast arrivals as pseudo-orders; "
             "it never reads the replay's future orders or actual durations.",
             f"{after['pseudo_orders']} forecast orders projected over the next {e.s.kitchen.window_min} min"]
    if after["lost_orders"]:
        notes.append(f"{after['lost_orders']} forecast orders would be turned away by this action")
    return {"date": d, "at": hm(e.t), "action": action,
            "headroom_pct_before": base["headroom_pct"], "headroom_pct_after": after["headroom_pct"],
            "late_orders_before": base["late_orders"], "late_orders_after": after["late_orders"],
            "late_minutes_before": base["late_minutes"], "late_minutes_after": after["late_minutes"],
            "lost_orders": after["lost_orders"], "notes": notes}


def run_day(d: str, settings: PresentSettings | None = None, write: bool = True) -> Engine:
    """Run a closed day in full (and write its ledger events)."""
    e = engine(d, 10 ** 6, settings)
    if write:
        flush(e)
    return e


def invalidate(d: str):
    """New overrides for date d (agent/manager actions): drop cached states and carry cached engines that have not
    yet reached the override minute over to the new key (no recompute)."""
    ov = overrides_for(d)
    suffix = (len(ov), str(ov[-1]["id"]) if ov else "")
    with _LOCK:
        for k in [k for k in _STATES if k[0] == d]:
            _STATES.pop(k, None)
        for key, e in list(_ENGINES.items()):
            if key[0] != d or key[2] != "gondola" or key[3:] == suffix:
                continue
            known = {o.get("id") for lst in e.overrides.values() for o in lst}
            new = [o for o in ov if o.get("id") not in known]
            if not all(o["minute"] >= e.t for o in new):
                continue
            nk = key[:3] + suffix
            for eng in [e] + list(_CHECKPOINTS.get(key, {}).values()):
                for o in new:
                    eng.overrides.setdefault(int(o["minute"]), []).append(o)
            _ENGINES[nk] = e
            _CHECKPOINTS[nk] = _CHECKPOINTS.get(key, {})


def reset_cache():
    with _LOCK:
        _ENGINES.clear()
        _CHECKPOINTS.clear()
        _STATES.clear()
        _FLUSHED.clear()
        _ARR_CACHE.clear()
        _RUNOUT.clear()
