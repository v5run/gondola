from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OfferPolicy(BaseModel):
    """Agent-editable preferences. Safety, scoring and world state are not editable."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(default="Protect the rush", min_length=1, max_length=60)
    load_weight: float = Field(default=7.0, ge=0, le=20)
    minimum_margin_cents: int = Field(default=350, ge=0, le=1500)
    reserve_minutes: int = Field(default=3, ge=0, le=12)
    discount_cents: int = Field(default=100, ge=0, le=200)
    max_station_load: float = Field(default=0.9, ge=0.2, le=1.5)


class RushRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    scenario: Literal["rush", "balanced", "overload", "quiet"] = "rush"
    seed: int = Field(default=7, ge=0, le=1_000_000)
    incident: Literal["fryer_slowdown", "courier_delay", "station_outage", "none"] = "fryer_slowdown"
    incident_at: int = Field(default=12, ge=4, le=35)
    budget_cents: int = Field(default=1200, ge=0, le=5000)
    cooks: int = Field(default=3, ge=1, le=4)
    forecast_pressure: float = Field(default=1.0, ge=0.25, le=2.0)
    policy: OfferPolicy = Field(default_factory=OfferPolicy)


class AgentRequest(RushRequest):
    minute: int = Field(default=12, ge=0, le=45)


class LabRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str = Field(default="Improve contribution while protecting accepted pickup promises.", max_length=500)
