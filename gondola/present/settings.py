"""Per-store Present settings: ladder thresholds, hysteresis, queue factor weights, kitchen and pricing knobs.

Stored under the "present" key of out/settings.json (other keys in that file are preserved). Defaults live here in
code; GET/PUT /api/present/settings reads and writes them. Override the file with GONDOLA_SETTINGS_PATH (tests).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..paths import ROOT

_LOCK = threading.Lock()


class Ladder(BaseModel):
    """Headroom thresholds in percent. Above promote_above: promote; quote_below..0: quote longer; and so on."""
    model_config = ConfigDict(extra="forbid")
    promote_above: float = Field(20.0, ge=-100, le=100)
    quote_below: float = Field(0.0, ge=-100, le=100)
    pause_below: float = Field(-10.0, ge=-100, le=100)
    busy_below: float = Field(-25.0, ge=-100, le=100)
    hysteresis_min: int = Field(2, ge=0, le=30)
    release_margin_pct: float = Field(3.0, ge=0, le=30, description="extra headroom needed before relaxing a step")

    @model_validator(mode="after")
    def _ordered(self):
        if not (self.promote_above > self.quote_below > self.pause_below > self.busy_below):
            raise ValueError("ladder thresholds must satisfy promote_above > quote_below > pause_below > busy_below")
        return self


class Weights(BaseModel):
    """Queue factor weights. Each factor is a number of minutes added to an order's slack (negative = sooner)."""
    model_config = ConfigDict(extra="forbid")
    courier: float = Field(1.0, ge=0, le=5, description="far courier adds slack (capped), arriving courier removes it")
    courier_far_cap_min: float = Field(8.0, ge=0, le=30)
    courier_arriving_min: float = Field(3.0, ge=0, le=15, description="bump when the courier is within 2 min / here")
    distance: float = Field(0.5, ge=0, le=5, description="minutes of slack per km of customer drive beyond 3 km")
    hold: float = Field(1.0, ge=0, le=5, description="low hold tolerance -> start later when there is slack")
    weather: float = Field(1.0, ge=0, le=5, description="rain/snow ETA-uncertainty buffer multiplier")
    rain_buffer_min: float = Field(3.0, ge=0, le=15)
    snow_buffer_min: float = Field(5.0, ge=0, le=20)
    cold_hold_factor: float = Field(0.7, ge=0.1, le=1.0, description="hold tolerance multiplier below cold_temp_c")
    cold_temp_c: float = Field(3.0, ge=-30, le=20)
    batch: float = Field(1.0, ge=0, le=5, description="bump for same-station, same-item work due within the window")
    batch_window_min: float = Field(3.0, ge=0, le=15)
    fairness: float = Field(1.0, ge=0, le=5, description="1 = enforce max_wait_min exactly (Savvy's age protection)")
    in_store: float = Field(4.0, ge=0, le=15, description="minutes of bump for a guest physically in the store")
    urgent_slack_min: float = Field(1.0, ge=-10, le=15, description="orders at or below this slack are served first, by "
                                    "slack (and the fairness cap) only: bumps never push an at-risk order past its start")
    reshuffle_margin_min: float = Field(1.5, ge=0, le=10, description="next-up work keeps its place unless beaten by this")


class Kitchen(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slots: dict[str, int] = Field(default_factory=lambda: {"noodles": 12, "fryer": 4, "assembly": 2, "packing": 3})
    line_share: float = Field(0.5, ge=0.1, le=1.0, description="share of scheduled cook hours on the line")
    min_cooks: int = Field(2, ge=1, le=20)
    max_cooks: int = Field(8, ge=1, le=30)
    dine_in_target_min: int = Field(12, ge=5, le=40)
    window_min: int = Field(30, ge=10, le=90, description="headroom window")
    forecast_lead_min: int = Field(15, ge=0, le=30, description="arrivals in the last minutes of the window are not counted")
    jit_min_headroom_pct: float = Field(50.0, ge=-100, le=100, description="just-in-time starts only while headroom "
                                        "is at least this; below it the queue is work-conserving (start as early as fits)")
    safety_buffer_min: float = Field(2.0, ge=0, le=10, description="just-in-time starts aim this much before due; "
                                     "+1 in rain/snow, +1 while a station is slowed (uncertainty buffer)")


class Pricing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    budget_cents: int = Field(1200, ge=0, le=5000)
    discount_cents: int = Field(100, ge=0, le=200)
    every_min: int = Field(5, ge=1, le=60)


class Agent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger_headroom_pct: float = Field(-10.0, ge=-100, le=50)
    trigger_lookahead_min: int = Field(20, ge=5, le=60)
    min_gap_min: int = Field(10, ge=1, le=120, description="minimum minutes between agent runs in the service")
    action_ttl_min: int = Field(15, ge=5, le=60)
    courier_delay_cluster: int = Field(3, ge=2, le=20)
    courier_delay_min: float = Field(5.0, ge=1, le=30)


class PresentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ladder: Ladder = Field(default_factory=Ladder)
    weights: Weights = Field(default_factory=Weights)
    max_wait_min: int = Field(35, ge=10, le=120, description="fairness cap: no order waits past this age")
    kitchen: Kitchen = Field(default_factory=Kitchen)
    pricing: Pricing = Field(default_factory=Pricing)
    agent: Agent = Field(default_factory=Agent)

    def digest(self) -> str:
        import hashlib
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:10]


def path() -> Path:
    p = os.getenv("GONDOLA_SETTINGS_PATH")
    return Path(p) if p else ROOT / "out" / "settings.json"


def _read_file() -> dict:
    p = path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def load() -> PresentSettings:
    raw = _read_file().get("present")
    if not raw:
        return PresentSettings()
    try:
        return PresentSettings.model_validate(raw)
    except Exception:  # a broken file never takes the controller down; defaults apply
        return PresentSettings()


def merge(patch: dict) -> PresentSettings:
    """Deep-merge a partial update into the current settings and validate (raises ValueError on bad input)."""
    cur = load().model_dump()

    def deep(a: dict, b: dict):
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                deep(a[k], v)
            else:
                a[k] = v
    deep(cur, patch or {})
    return PresentSettings.model_validate(cur)


def save(s: PresentSettings) -> PresentSettings:
    with _LOCK:
        data = _read_file()
        data["present"] = s.model_dump()
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(p)
    return s
