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
    cash = pd.DataFrame(json.loads((raw / "cash_drawer_shifts.json").read_text(encoding="utf-8"))["cash_drawer_shifts"])
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


def cut(upto: str, db_path: Path, src: Path = DB) -> Path:
    """Same result as `ingest(db_path=..., upto=...)`, but copied from an already-built database instead of re-reading
    data/raw (about 50x faster). Used by the history backfill to give each past close the data that existed that night.
    Tables with a business_date keep rows up to `upto`; order lines follow their orders; reference tables are copied."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    try:
        con.execute(f"ATTACH '{Path(src).as_posix()}' AS src (READ_ONLY)")
        tabs = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog = 'src'").fetchall()]
        cutoff = str(pd.Timestamp(upto).date())
        for t in tabs:
            cols = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_catalog='src' "
                                               "AND table_name = ?", [t]).fetchall()}
            if "business_date" in cols:
                con.execute(f"CREATE TABLE {t} AS SELECT * FROM src.{t} WHERE business_date <= TIMESTAMP '{cutoff}'")
            elif t == "order_lines":
                continue
            else:
                con.execute(f"CREATE TABLE {t} AS SELECT * FROM src.{t}")
        if "order_lines" in tabs:
            con.execute("CREATE TABLE order_lines AS SELECT l.* FROM src.order_lines l "
                        "WHERE l.order_id IN (SELECT order_id FROM orders)")
        con.execute("DETACH src")
    finally:
        con.close()
    return db_path


if __name__ == "__main__":
    print(ingest())
