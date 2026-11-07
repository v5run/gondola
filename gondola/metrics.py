"""Metrics layer: every number comes from one YAML definition, computed in DuckDB."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFS = yaml.safe_load((Path(__file__).parent / "metrics.yaml").read_text(encoding="utf-8"))
GRAINS = {"day": "business_date", "channel": "channel", "hour": "hour", "item": "item", "dow": "dow"}


class Store:
    """Read-only access to one store's normalized database."""

    def __init__(self, db_path: Path | str = ROOT / "data" / "gondola.duckdb"):
        self.db_path = str(db_path)
        self.con = duckdb.connect(self.db_path, read_only=True)

    def df(self, sql: str, params: list | None = None) -> pd.DataFrame:
        return self.con.execute(sql, params or []).df()

    @lru_cache(maxsize=1)
    def last_date(self) -> pd.Timestamp:
        return pd.Timestamp(self.df("SELECT max(business_date) d FROM orders").d[0])

    # ------------------------------------------------------------------ typed metric API
    def query_metric(self, metric: str, start: str, end: str, grain: str = "day", channel: str | None = None) -> pd.DataFrame:
        """Return metric values between start and end (inclusive) at the given grain."""
        if metric not in DEFS:
            raise KeyError(f"unknown metric '{metric}'. Known: {sorted(DEFS)}")
        if grain not in GRAINS:
            raise KeyError(f"unknown grain '{grain}'")
        d = DEFS[metric]
        src = d["from"]
        if src == "orders":
            base = "SELECT o.*, extract(hour FROM created_at) AS hour, dayofweek(business_date) AS dow FROM orders o"
        elif src == "payout_lines":  # only reports that have arrived by the end of the latest business day
            base = (f"SELECT *, dayofweek(business_date) AS dow FROM payout_lines WHERE CAST(available_at AS TIMESTAMP) <= "
                    f"TIMESTAMP '{self.last_date():%Y-%m-%d} 23:59:59'")
        else:
            base = f"SELECT *, dayofweek(business_date) AS dow FROM {src}"
        if grain == "item":
            if src != "orders":
                raise ValueError("item grain only for order metrics")
            sql_expr = d["sql"].replace("subtotal", "l.price").replace("status", "o.status")
            base = ("SELECT o.status, o.channel, o.business_date, l.item, l.price FROM orders o "
                    "JOIN order_lines l USING(order_id)")
            if metric == "orders":
                sql_expr = "SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END)"
            elif metric == "net_sales":
                sql_expr = "SUM(CASE WHEN status='completed' THEN price ELSE 0 END)"
        else:
            sql_expr = d["sql"]
        where = ["business_date BETWEEN ? AND ?"]
        params: list = [start, end]
        if channel:
            if src == "labour":
                raise ValueError("labour has no channel")
            where.append("channel = ?")
            params.append(channel)
        g = GRAINS[grain]
        sql = f"SELECT {g} AS key, {sql_expr} AS value FROM ({base}) t WHERE {' AND '.join(where)} GROUP BY 1 ORDER BY 1"
        return self.df(sql, params)

    def metric_total(self, metric: str, start: str, end: str | None = None, channel: str | None = None) -> float:
        end = end or start
        d = DEFS[metric]
        if metric == "avg_ticket":
            s = self.metric_total("net_sales", start, end, channel)
            n = self.metric_total("orders", start, end, channel)
            return s / n if n else 0.0
        v = self.query_metric(metric, start, end, "day", channel).value.sum()
        return float(v)

    def daily_frame(self) -> pd.DataFrame:
        """One row per business day with the core metrics and context. Used by Analyst, Demand and Ask."""
        q = """
        WITH o AS (
          SELECT business_date,
                 SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS orders,
                 SUM(CASE WHEN status='completed' THEN subtotal ELSE 0 END) AS net_sales,
                 SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) AS cancels,
                 SUM(CASE WHEN status='cancelled' AND cancel_reason='item_unavailable' THEN 1 ELSE 0 END) AS avoidable_cancels,
                 SUM(CASE WHEN channel='doordash' THEN 1 ELSE 0 END) AS dd_orders
          FROM orders GROUP BY 1),
        lab AS (SELECT business_date, SUM(hours*wage) AS labour_cost, SUM(hours) AS labour_hours FROM labour GROUP BY 1)
        SELECT o.*, lab.labour_cost, lab.labour_hours FROM o LEFT JOIN lab USING(business_date) ORDER BY 1"""
        df = self.df(q)
        cal = self.df("SELECT * FROM calendar")
        ev = self.df("SELECT date, max(lift) AS event_lift, string_agg(event, '; ') AS events, "
                     "max(CASE WHEN event LIKE 'Penguins%' THEN 1 ELSE 0 END) AS penguins, "
                     "max(CASE WHEN event LIKE 'Steelers%' THEN 1 ELSE 0 END) AS steelers FROM events GROUP BY 1")
        df = df.merge(cal, left_on="business_date", right_on="date", how="left").drop(columns=["date"])
        df = df.merge(ev, left_on="business_date", right_on="date", how="left").drop(columns=["date"])
        df[["event_lift"]] = df[["event_lift"]].fillna(1.0)
        df[["penguins", "steelers"]] = df[["penguins", "steelers"]].fillna(0)
        df["avg_ticket"] = df.net_sales / df.orders
        df["labour_pct"] = df.labour_cost / df.net_sales
        return df
