from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    scenario: Literal["rush", "quiet", "overload"] = "rush"
    seed: int = Field(default=7, ge=0, le=1_000_000)
    cooks: int = Field(default=3, ge=1, le=4)
    budget_cents: int = Field(default=1200, ge=0, le=5000)
    max_discount_cents: int = Field(default=300, ge=0, le=300)
    quote_ttl_seconds: int = Field(default=180, ge=5, le=600)


class CartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cart_id: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    item: Literal["don", "tonkotsu", "karaage", "gyoza"] = "don"
    latest_pickup_minute: int = Field(default=70, ge=15, le=180)
    minimum_saving_cents: int = Field(default=200, ge=100, le=500)


class AcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_id: str = Field(min_length=1, max_length=100)
