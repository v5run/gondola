"""The Ledger ("Past"): an append-only, typed event log every workflow reads and writes.

Deterministic, no LLM. SQLite at out/ledger.sqlite (override with GONDOLA_LEDGER_DB). Events are keyed by business
date and a store-local timestamp. Writers must be idempotent: pass a stable `key` (e.g. "order.accepted:o0123") and a
repeated append with the same key is ignored, so replays and re-runs never double count.

Event types (payload fields are free-form JSON but should follow docs/architecture/TRI_WORKFLOW_API.md):
  order.received | order.accepted | order.quoted | order.deferred | order.declined | order.handed_off |
  order.cancelled | order.refunded | task.started | task.finished | courier.eta_updated | courier.arrived |
  customer.arrived | action.applied | forecast.issued | payout.report_arrived | cash.counted |
  exception.raised | exception.resolved | review.completed | kb.changed
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from ..paths import ROOT

_LOCK = threading.Lock()


def out_dir() -> Path:
    """The app's out/ folder: gondola.pipeline.OUT when the pipeline is loaded (tests and the history backfill point it
    at a temp/staging folder, and the ledger, knowledge base and digests follow it), else ROOT/out."""
    m = sys.modules.get("gondola.pipeline")
    return Path(getattr(m, "OUT", ROOT / "out")) if m is not None else ROOT / "out"


def db_path() -> Path:
    p = os.getenv("GONDOLA_LEDGER_DB")
    return Path(p) if p else out_dir() / "ledger.sqlite"


@dataclass
class Event:
    id: int
    date: str          # business date YYYY-MM-DD
    ts: str            # store-local ISO timestamp "YYYY-MM-DDTHH:MM:SS"
    type: str
    source: str        # "present" | "future" | "review" | "books" | "adapter:doordash" | ...
    key: str | None
    payload: dict

    def to_dict(self) -> dict:
        return {"id": self.id, "date": self.date, "ts": self.ts, "type": self.type, "source": self.source,
                "key": self.key, "payload": self.payload}


class Ledger:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, ts TEXT NOT NULL, type TEXT NOT NULL,
                source TEXT NOT NULL, key TEXT UNIQUE, payload TEXT NOT NULL)""")
            c.execute("CREATE INDEX IF NOT EXISTS ix_date_type ON events(date, type)")
            c.execute("CREATE INDEX IF NOT EXISTS ix_date_ts ON events(date, ts)")

    def _con(self):
        c = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def append(self, type: str, date: str, ts: str, payload: dict | None = None, source: str = "system",
               key: str | None = None) -> int | None:
        """Append one event. Returns its id, or None if `key` was already recorded."""
        with _LOCK, self._con() as c:
            cur = c.execute("INSERT OR IGNORE INTO events(date, ts, type, source, key, payload) VALUES (?,?,?,?,?,?)",
                            (date, ts, type, source, key, json.dumps(payload or {}, default=str)))
            return cur.lastrowid if cur.rowcount else None

    def extend(self, rows: list[dict]) -> int:
        """Bulk append: rows of {type, date, ts, payload, source, key}. Returns how many were new."""
        with _LOCK, self._con() as c:
            before = c.total_changes
            c.executemany("INSERT OR IGNORE INTO events(date, ts, type, source, key, payload) VALUES (?,?,?,?,?,?)",
                          [(r["date"], r["ts"], r["type"], r.get("source", "system"), r.get("key"),
                            json.dumps(r.get("payload") or {}, default=str)) for r in rows])
            return c.total_changes - before

    def query(self, date: str | None = None, types: list[str] | None = None, start_ts: str | None = None,
              end_ts: str | None = None, limit: int | None = None, newest_first: bool = False,
              before_id: int | None = None, source: str | None = None) -> list[Event]:
        """before_id: only events with a smaller id (paging newest first). source: only this writer."""
        where, args = [], []
        if before_id is not None:
            where.append("id < ?"); args.append(int(before_id))
        if source:
            where.append("source = ?"); args.append(source)
        if date:
            where.append("date = ?"); args.append(date)
        if types:
            where.append(f"type IN ({','.join('?' * len(types))})"); args += types
        if start_ts:
            where.append("ts >= ?"); args.append(start_ts)
        if end_ts:
            where.append("ts <= ?"); args.append(end_ts)
        sql = "SELECT id, date, ts, type, source, key, payload FROM events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY ts {'DESC' if newest_first else 'ASC'}, id {'DESC' if newest_first else 'ASC'}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self._con() as c:
            rows = c.execute(sql, args).fetchall()
        return [Event(r[0], r[1], r[2], r[3], r[4], r[5], json.loads(r[6])) for r in rows]

    def dates(self, types: list[str] | None = None) -> list[str]:
        """Business dates that have events (of these types)."""
        sql, args = "SELECT DISTINCT date FROM events", []
        if types:
            sql += f" WHERE type IN ({','.join('?' * len(types))})"; args = list(types)
        with self._con() as c:
            return [r[0] for r in c.execute(sql + " ORDER BY date", args).fetchall()]

    def count(self, date: str | None = None, types: list[str] | None = None) -> int:
        where, args = [], []
        if date:
            where.append("date = ?"); args.append(date)
        if types:
            where.append(f"type IN ({','.join('?' * len(types))})"); args += types
        with self._con() as c:
            return c.execute("SELECT COUNT(*) FROM events" + (" WHERE " + " AND ".join(where) if where else ""), args).fetchone()[0]

    def clear_date(self, date: str, sources: list[str] | None = None) -> None:
        """Remove a day's events (used when rebuilding a demo day). Optionally only some sources."""
        with _LOCK, self._con() as c:
            if sources:
                c.execute(f"DELETE FROM events WHERE date = ? AND source IN ({','.join('?' * len(sources))})", [date, *sources])
            else:
                c.execute("DELETE FROM events WHERE date = ?", (date,))


_DEFAULT: Ledger | None = None


def ledger() -> Ledger:
    """Process-wide default ledger (respects GONDOLA_LEDGER_DB)."""
    global _DEFAULT
    if _DEFAULT is None or _DEFAULT.path != db_path():
        _DEFAULT = Ledger()
    return _DEFAULT
