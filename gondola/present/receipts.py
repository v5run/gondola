"""Durable Rush-agent receipts and applied overrides (the pattern of Savvy's gondola/rush/store.py: local SQLite,
no provider keys or hidden world state stored). Separate file so Savvy's Rush Control history stays its own.

overrides: actions the Rush agent (or a manager) applied to a live service at a minute. The replay applies them at
that minute, so every client sees the same deterministic day. GONDOLA_PRESENT_DB overrides the path (tests).
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..paths import ROOT


def db_path() -> Path:
    p = os.getenv("GONDOLA_PRESENT_DB")
    return Path(p) if p else ROOT / ".local" / "present-agent.sqlite3"


def _connect():
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=15)
    con.execute("CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, date TEXT NOT NULL, minute INTEGER, kind TEXT NOT NULL, "
                "status TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS overrides (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, minute INTEGER NOT NULL, "
                "action TEXT NOT NULL, by TEXT NOT NULL, receipt_id TEXT)")
    return con


def save(date: str, minute: int | None, kind: str, status: str, payload: dict, ident: str | None = None) -> str:
    ident = ident or uuid.uuid4().hex[:16]
    with _connect() as con:
        con.execute("INSERT OR REPLACE INTO receipts VALUES (?,?,?,?,?,?,?)",
                    (ident, date, minute, kind, status, datetime.now(timezone.utc).isoformat(), json.dumps(payload, default=str)))
    return ident


def get(ident: str) -> dict | None:
    with _connect() as con:
        r = con.execute("SELECT id,date,minute,kind,status,created,payload FROM receipts WHERE id=?", (ident,)).fetchone()
    if not r:
        return None
    return {**json.loads(r[6]), "id": r[0], "date": r[1], "minute": r[2], "kind": r[3], "status": r[4], "created": r[5]}


def recent(date: str | None = None, limit: int = 20) -> list[dict]:
    with _connect() as con:
        if date:
            rows = con.execute("SELECT id,date,minute,kind,status,created FROM receipts WHERE date=? ORDER BY created DESC LIMIT ?",
                               (date, limit)).fetchall()
        else:
            rows = con.execute("SELECT id,date,minute,kind,status,created FROM receipts ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
    return [dict(zip(("id", "date", "minute", "kind", "status", "created"), r)) for r in rows]


def add_override(date: str, minute: int, action: dict, by: str, receipt_id: str | None = None) -> int:
    with _connect() as con:
        cur = con.execute("INSERT INTO overrides(date, minute, action, by, receipt_id) VALUES (?,?,?,?,?)",
                          (date, int(minute), json.dumps(action), by, receipt_id))
        return int(cur.lastrowid)


def overrides(date: str) -> list[dict]:
    p = db_path()
    if not p.exists():
        return []
    with _connect() as con:
        rows = con.execute("SELECT id, minute, action, by, receipt_id FROM overrides WHERE date=? ORDER BY id", (date,)).fetchall()
    return [{"id": r[0], "minute": r[1], "action": json.loads(r[2]), "by": r[3], "receipt_id": r[4]} for r in rows]
