"""Connectors: turn raw source files into one normalized DuckDB database.

In production these are adapters for Square / Toast / middleware webhooks and Report Builder CSVs.
Here they read data/raw/ (see gondola.datagen). Each adapter maps its source into the same schema.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "gondola.duckdb"

DD_COLS = {"DoorDash order ID (POS ref)": "order_id", "Timestamp local date": "business_date", "Subtotal": "subtotal",
           "Commission": "commission", "Marketing fees": "marketing_fee", "Error charges": "error_charge",
           "Adjustments": "adjustment", "Net total": "net_payout", "Final order status": "status"}


def load_payouts(raw: Path = RAW) -> pd.DataFrame:
    frames = []
    for ch in ("doordash", "ubereats", "grubhub"):
        f = raw / f"{ch}_payout_report.csv"
        if not f.exists():
            continue
        p = pd.read_csv(f)
        if ch == "doordash":
            p = p.rename(columns=DD_COLS)
        p["channel"] = ch
        frames.append(p)
    out = pd.concat(frames, ignore_index=True)
    out["business_date"] = pd.to_datetime(out.business_date)
    return out


# Prior multipliers for holidays (industry rules of thumb, not learned: one year has each holiday once).
HOLIDAY_PRIOR = {"Thanksgiving": 0.5, "Black Friday": 1.05, "Christmas Eve": 0.75, "Christmas (closed)": 0.0,
                 "New Year's Eve": 0.9, "New Year's Day": 0.85, "Valentine's Day": 1.05, "Memorial Day": 0.9,
                 "Independence Day": 0.8, "Labor Day": 0.8}


def add_holiday_prior(cal: pd.DataFrame) -> pd.DataFrame:
    cal["holiday_factor"] = cal.holiday.map(HOLIDAY_PRIOR).fillna(1.0)
    return cal


def payouts_dedupe(p: pd.DataFrame) -> pd.DataFrame:
    """Platforms sometimes resend lines; keep one line per order and channel."""
    return p.drop_duplicates(subset=["channel", "order_id"], keep="last")


def ingest(raw: Path = RAW, db_path: Path = DB, upto: str | None = None) -> Path:
    """Build the database. `upto` limits history (used to simulate a past close)."""
    orders = pd.read_csv(raw / "pos_orders.csv", parse_dates=["business_date"])
    # convert to store-local wall time (sources may send UTC or local with offset)
    orders["created_at"] = pd.to_datetime(orders.created_at, utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
    lines = pd.read_csv(raw / "pos_order_lines.csv")
    payouts = payouts_dedupe(load_payouts(raw))
    cash = pd.DataFrame(json.loads((raw / "cash_drawer_shifts.json").read_text())["cash_drawer_shifts"])
    cash["business_date"] = pd.to_datetime(cash.business_date)
    tables = {
        "orders": orders,
        "order_lines": lines,
        "payout_lines": payouts,
        "cash_drawer_shifts": cash,
        "labour": pd.read_csv(raw / "labour_shifts.csv", parse_dates=["business_date"]),
        "invoices": pd.read_csv(raw / "invoices.csv", parse_dates=["business_date", "received_at"]),
        "waste": pd.read_csv(raw / "waste_log.csv", parse_dates=["business_date"]),
        "counts": pd.read_csv(raw / "counts.csv", parse_dates=["business_date"]),
        "calendar": add_holiday_prior(pd.read_csv(raw / "weather_calendar.csv", parse_dates=["date"])),
        "events": pd.read_csv(raw / "events.csv", parse_dates=["date"]),
        "menu": pd.read_csv(raw / "menu.csv"),
        "skus": pd.read_csv(raw / "skus.csv"),
        "recipes": pd.read_csv(raw / "recipes.csv"),
        "prep_log": pd.read_csv(raw / "prep_log.csv", parse_dates=["business_date"]),
    }
    if upto:
        cut = pd.Timestamp(upto)
        for name, df in tables.items():
            if "business_date" in df.columns:
                tables[name] = df[df.business_date <= cut]
        tables["order_lines"] = lines[lines.order_id.isin(tables["orders"].order_id)]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    for name, df in tables.items():
        con.register("tmp", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM tmp")
        con.unregister("tmp")
    con.close()
    return db_path


if __name__ == "__main__":
    print(ingest())
