from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..rush.engine import MENU

Channel = Literal["doordash", "ubereats", "dine_in", "pickup"]
Item = Literal["tonkotsu", "karaage", "gyoza", "don"]
Strategy = Literal["current", "arrival", "promise", "slack"]
Identifier = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Line(StrictModel):
    item: Item
    quantity: int = Field(default=1, ge=1, le=10, strict=True)


class IncomingOrder(StrictModel):
    order_id: Identifier
    channel: Channel
    received_minute: int = Field(ge=0, le=240, strict=True)
    requested_ready_minute: int = Field(ge=1, le=360, strict=True)
    latest_ready_minute: int | None = Field(default=None, ge=1, le=360, strict=True)
    items: list[Line] = Field(min_length=1, max_length=8)
    commitment: Literal["request", "confirmed"] = "request"

    @model_validator(mode="after")
    def timing(self):
        latest = self.latest_ready_minute or self.requested_ready_minute
        if not self.received_minute < self.requested_ready_minute <= latest <= self.received_minute + 120:
            raise ValueError("Ready window must follow receipt and stay within 120 minutes")
        if sum(line.quantity for line in self.items) > 20:
            raise ValueError("At most 20 portions per order in this bounded workflow")
        if len({line.item for line in self.items}) != len(self.items):
            raise ValueError("Combine duplicate menu lines into a single quantity")
        return self

    @property
    def key(self) -> str:
        return f"{self.channel}:{self.order_id}"


class Policy(StrictModel):
    cooks: int = Field(default=3, ge=1, le=4, strict=True)
    reserve_minutes: int = Field(default=2, ge=0, le=10, strict=True)
    max_lead_minutes: int = Field(default=60, ge=15, le=120, strict=True)
    response_minutes: int = Field(default=2, ge=1, le=5, strict=True)
    default_priority: Strategy = "arrival"


class Task(StrictModel):
    id: str
    station: str
    item: str
    nominal: float
    start: int | None = None
    end: int | None = None
    progress: float = 0


class ManagedOrder(StrictModel):
    request: IncomingOrder
    status: Literal["pending", "accepted", "declined", "expired", "completed"] = "pending"
    promise: int | None = None
    decision: str | None = None
    reason: str = "Awaiting a checked admission decision"
    tasks: list[Task] = Field(default_factory=list)


class Session(StrictModel):
    revision: int = 0
    minute: int = 0
    policy: Policy = Field(default_factory=Policy)
    orders: list[ManagedOrder] = Field(default_factory=list)
    priority: list[str] = Field(default_factory=list)
    stock: dict[str, int] = Field(default_factory=lambda: {k: v["stock"] for k, v in MENU.items()})
    speeds: dict[str, float] = Field(default_factory=lambda: {s: 1.0 for s in ("fryer", "noodles", "assembly", "packing")})
    blocked_until: dict[str, int] = Field(default_factory=dict)
    receipts: list[dict] = Field(default_factory=list)
    # Never drop dedupe keys while a session remains mutable.
    events: dict[str, dict] = Field(default_factory=dict)


class CreateSession(StrictModel):
    policy: Policy = Field(default_factory=Policy)
    demo_burst: bool = False


class Command(StrictModel):
    event_id: Identifier
    revision: int = Field(ge=0, strict=True)


class Intake(Command):
    orders: list[IncomingOrder] = Field(min_length=1, max_length=60)


class ApplyPlan(Command):
    strategy: Strategy
    plan_id: str = Field(min_length=16, max_length=64)


class Advance(Command):
    minute: int = Field(ge=0, le=240, strict=True)


class CapacityChange(Command):
    station: Literal["fryer", "noodles", "assembly", "packing"]
    speed: float = Field(ge=0.25, le=2)
    unavailable_minutes: int = Field(default=0, ge=0, le=30, strict=True)


class AgentCommand(StrictModel):
    revision: int = Field(ge=0, strict=True)
