"""Square connector (sandbox by default), plain REST.

- orders_for_date(): completed orders for a business date -> Gondola's POS order schema (orders + lines)
- cash_drawer_shifts(): shifts for a date -> Gondola's cash_drawer_shifts schema (expected vs counted)
- Writes, including sold-out and sandbox order seeding, are disabled pending an authenticated approval design.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from ..config import Settings, get_settings

VERSION = "2025-10-16"
TZ = ZoneInfo("America/New_York")
CHANNEL_HINTS = {"doordash": "doordash", "door dash": "doordash", "uber": "ubereats", "grubhub": "grubhub"}


class SquareError(RuntimeError):
    pass


class SquareClient:
    def __init__(self, s: Settings | None = None, session: requests.Session | None = None):
        self.s = s or get_settings()
        self.base = "https://connect.squareupsandbox.com" if self.s.square_env != "production" else "https://connect.squareup.com"
        self.http = session or requests.Session()

    @property
    def live(self) -> bool:
        return self.s.square_live

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.s.square_access_token}", "Square-Version": VERSION,
                "Content-Type": "application/json"}

    def _req(self, method: str, path: str, **kw) -> dict:
        # Square uses POST for order search, but all other POSTs are writes.
        if method.upper() != "GET" and not (method.upper() == "POST" and path == "/v2/orders/search"):
            raise SquareError("Merchant writes are disabled pending authenticated manager approval")
        r = self.http.request(method, self.base + path, headers=self._h(), timeout=20, **kw)
        if r.status_code >= 300:
            raise SquareError(f"Square {r.status_code}")
        return r.json()

    # ------------------------------------------------------------------ reads
    @staticmethod
    def day_window(date: str) -> tuple[str, str]:
        start = datetime.fromisoformat(date).replace(hour=4, tzinfo=TZ)  # business day runs 4 am to 4 am
        end = start + timedelta(days=1)
        f = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return f(start), f(end)

    def raw_orders(self, date: str) -> list[dict]:
        a, b = self.day_window(date)
        body = {"location_ids": [self.s.square_location_id], "limit": 500,
                "query": {"filter": {"date_time_filter": {"created_at": {"start_at": a, "end_at": b}},
                                     "state_filter": {"states": ["COMPLETED", "CANCELED"]}},
                          "sort": {"sort_field": "CREATED_AT", "sort_order": "ASC"}}}
        out, cursor = [], None
        while True:
            if cursor:
                body["cursor"] = cursor
            j = self._req("POST", "/v2/orders/search", json=body)
            out += j.get("orders", [])
            cursor = j.get("cursor")
            if not cursor:
                return out

    def orders_for_date(self, date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        return map_orders(self.raw_orders(date), date)

    def cash_drawer_shifts(self, date: str) -> pd.DataFrame:
        a, b = self.day_window(date)
        j = self._req("GET", "/v2/cash-drawers/shifts", params={"location_id": self.s.square_location_id,
                                                               "begin_time": a, "end_time": b, "limit": 200})
        details = [self._req("GET", f"/v2/cash-drawers/shifts/{x['id']}",
                             params={"location_id": self.s.square_location_id}).get("cash_drawer_shift", {})
                   for x in j.get("cash_drawer_shifts", [])]
        return map_shifts(details, date)

    # ------------------------------------------------------------------ writes
    def set_sold_out(self, variation_id: str, sold_out: bool = True, quantity: int = 0) -> dict:
        change = {"type": "PHYSICAL_COUNT", "physical_count": {
            "catalog_object_id": variation_id, "location_id": self.s.square_location_id, "state": "IN_STOCK",
            "quantity": "0" if sold_out else str(quantity),
            "occurred_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}}
        return self._req("POST", "/v2/inventory/changes/batch-create",
                         json={"idempotency_key": str(uuid.uuid4()), "changes": [change]})

    def seed_demo_orders(self, n: int = 20, date: str = "2026-11-05", store=None) -> list[str]:
        """Disabled: even sandbox order creation is an external write."""
        raise SquareError("Demo order creation is disabled pending authenticated manager approval")



# ---------------------------------------------------------------------- mapping (pure, tested offline)
def _money(m: dict | None) -> float:
    return round((m or {}).get("amount", 0) / 100, 2)


def channel_of(order: dict) -> str:
    name = ((order.get("source") or {}).get("name") or "").lower()
    for hint, ch in CHANNEL_HINTS.items():
        if hint in name:
            return ch
    return "in_store"


def map_orders(raw: list[dict], business_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Square orders -> (orders, order_lines) in Gondola's schema."""
    orders, lines = [], []
    for o in raw:
        tenders = o.get("tenders") or []
        tender = None
        if tenders:
            tender = "cash" if tenders[0].get("type") == "CASH" else "card"
        created = pd.Timestamp(o["created_at"]).tz_convert("America/New_York").tz_localize(None)
        subtotal = sum(_money(li.get("base_price_money")) * float(li.get("quantity", "1")) for li in o.get("line_items", []))
        orders.append({"order_id": o.get("reference_id") or o["id"], "business_date": pd.Timestamp(business_date),
                       "created_at": created, "channel": channel_of(o), "subtotal": round(subtotal, 2),
                       "tax": _money(o.get("total_tax_money")), "tip": _money(o.get("total_tip_money")), "tender": tender,
                       "status": "completed" if o.get("state") == "COMPLETED" else "cancelled",
                       "cancel_reason": None if o.get("state") == "COMPLETED" else "pos_cancelled", "promo": False})
        for li in o.get("line_items", []):
            for _ in range(int(float(li.get("quantity", "1")))):
                lines.append({"order_id": o.get("reference_id") or o["id"], "item": li.get("name"),
                              "price": _money(li.get("base_price_money"))})
    return pd.DataFrame(orders), pd.DataFrame(lines)


def map_shifts(details: list[dict], business_date: str) -> pd.DataFrame:
    rows = []
    for d in details:
        rows.append({"shift_id": d.get("id"), "business_date": pd.Timestamp(business_date), "state": d.get("state"),
                     "opened_at": d.get("opened_at"), "ended_at": d.get("ended_at") or d.get("closed_at"),
                     "opening_cash": _money(d.get("opened_cash_money")), "cash_payments": _money(d.get("cash_payment_money")),
                     "paid_out": _money(d.get("cash_paid_out_money")), "expected_cash": _money(d.get("expected_cash_money")),
                     "closed_cash": _money(d.get("closed_cash_money")) if d.get("closed_cash_money") else None})
    return pd.DataFrame(rows)
