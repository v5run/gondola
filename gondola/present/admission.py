"""Admission ladder: how much work to accept, and when (design TRI_WORKFLOW.md section 3.3).

Levels (headroom thresholds are per-store settings, out/settings.json):
   1 promote  headroom above promote_above: Savvy's pricing may feature items on idle stations (own channels)
   0 normal
  -1 quote    quote longer prep times on delivery apps by the predicted delay
  -2 pause    pause slow items on the binding station on delivery apps, Grubhub first (its pause is slowest)
  -3 busy     busy mode per app, cheapest-contribution app first; stop all promotions. Never dine-in or pickup.
Hysteresis: a new level must persist for `hysteresis_min` minutes before the controller moves, and relaxing a step
needs `release_margin_pct` extra headroom, so the ladder doesn't flap.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .world import DELIVERY_APPS, MENU

LEVELS = {1: "promote", 0: "normal", -1: "quote", -2: "pause", -3: "busy"}
# Modeled propagation delay of an item pause / busy mode per app (minutes). Grubhub's is slowest, so it goes first.
PROPAGATION = {"grubhub": 4, "ubereats": 2, "doordash": 1}
PAUSE_ORDER = ["grubhub", "ubereats", "doordash"]
NEVER = ("dine_in", "pickup")


def target_level(h: float, ladder) -> int:
    if h > ladder.promote_above:
        return 1
    if h >= ladder.quote_below:
        return 0
    if h >= ladder.pause_below:
        return -1
    if h >= ladder.busy_below:
        return -2
    return -3


@dataclass
class LadderState:
    level: int = 0
    since: int = 0
    pending: int | None = None
    pending_since: int | None = None
    history: list = field(default_factory=list)

    def candidate(self, h: float, ladder) -> int:
        tighter = target_level(h, ladder)
        if tighter < self.level:
            return tighter
        relaxed = target_level(h - ladder.release_margin_pct, ladder)
        if relaxed > self.level:
            return relaxed
        return self.level

    def update(self, minute: int, h: float, ladder) -> tuple[int, int] | None:
        """Feed this minute's headroom. Returns (old, new) when the level changes."""
        c = self.candidate(h, ladder)
        if c == self.level:
            self.pending, self.pending_since = None, None
            return None
        same_dir = self.pending is not None and (self.pending - self.level) * (c - self.level) > 0
        if not same_dir:
            self.pending, self.pending_since = c, minute
        else:
            self.pending = c
        if minute - (self.pending_since or minute) >= ladder.hysteresis_min:
            old = self.level
            self.level, self.since = c, minute
            self.pending, self.pending_since = None, None
            self.history.append((minute, old, c, round(h, 1)))
            return old, c
        return None

    def next_threshold(self, ladder) -> dict:
        """Headroom values at which the level would move down (tighten) and up (relax)."""
        bounds = {1: (ladder.promote_above, None), 0: (ladder.quote_below, ladder.promote_above),
                  -1: (ladder.pause_below, ladder.quote_below), -2: (ladder.busy_below, ladder.pause_below),
                  -3: (None, ladder.busy_below)}
        lo, hi = bounds[self.level]
        return {"tighten_below": lo, "relax_above": None if hi is None else hi + ladder.release_margin_pct,
                "hysteresis_min": ladder.hysteresis_min}


def slow_items(station: str, durations: dict[str, float]) -> list[str]:
    """The two slowest items of a station (within a minute of its slowest). Labour/packing -> the fryer's."""
    pool = {k: v for k, v in durations.items() if MENU.get(k, {}).get("station") == station}
    if not pool:
        pool = {k: v for k, v in durations.items() if MENU.get(k, {}).get("station") == "fryer"}
    top = max(pool.values())
    return sorted([k for k, v in pool.items() if v >= top - 1.0], key=lambda k: (-pool[k], k))[:2]


def quote_extra(predicted_delay: float, headroom_pct: float, window: int) -> int:
    """Quote longer prep by the predicted delay, in 5-minute steps, 5..20."""
    est = max(predicted_delay, -headroom_pct / 100.0 * window)
    return int(min(20, max(5, 5 * math.ceil(max(est, 0.1) / 5))))


def cheapest_first(contribution: dict[str, float]) -> list[str]:
    """Delivery apps ordered by how little of each order the store keeps (lowest net payout share first)."""
    return sorted(DELIVERY_APPS, key=lambda a: (contribution.get(a, 0.75), a))


def channel_template() -> dict:
    return {a: {"state": "open", "quoted_extra_min": 0, "paused_items": [], "busy": False,
                "effective": {}} for a in DELIVERY_APPS}


def decide(channels: dict, app: str, items: list[str], minute: int) -> tuple[str, str, int]:
    """Admission of one new order at `minute`. Returns (decision, reason, extra_min);
    decision in accepted | quoted | declined. Dine-in and pickup are always accepted."""
    if app in NEVER or app not in channels:
        return "accepted", "own channel: always accepted (never throttled)", 0
    st = channels[app]
    eff = st.get("effective", {})
    if st.get("busy") and minute >= eff.get("busy", minute):
        return "declined", f"busy mode on {app}", 0
    paused = [i for i in items if i in st.get("paused_items", []) and minute >= eff.get("pause:" + i, minute)]
    if paused:
        return "declined", f"item paused on {app}: {', '.join(sorted(set(paused)))} (modeled as a lost order)", 0
    extra = int(st.get("quoted_extra_min") or 0)
    if extra:
        return "quoted", f"quoted +{extra} min prep on {app}", extra
    return "accepted", "within capacity", 0
