"""Local durable demo receipts; provider keys and private world state are never stored."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / ".local" / "rush-control.sqlite3"


def _connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=15)
    con.execute("CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL)")
    return con


def create(kind: str, payload: dict) -> str:
    ident = uuid.uuid4().hex
    with _connect() as con:
        con.execute("INSERT INTO artifacts VALUES (?,?,?,?,?)", (ident, kind, "running", datetime.now(timezone.utc).isoformat(), json.dumps(payload)))
    return ident


def update(ident: str, status: str, payload: dict):
    with _connect() as con:
        con.execute("UPDATE artifacts SET status=?, payload=? WHERE id=?", (status, json.dumps(payload), ident))


def get(ident: str) -> dict | None:
    with _connect() as con:
        row = con.execute("SELECT id,kind,status,created,payload FROM artifacts WHERE id=?", (ident,)).fetchone()
    return dict(id=row[0], kind=row[1], status=row[2], created=row[3], **json.loads(row[4])) if row else None


def recent() -> list[dict]:
    with _connect() as con:
        rows = con.execute("SELECT id,kind,status,created FROM artifacts WHERE kind != 'comparison' ORDER BY created DESC LIMIT 20").fetchall()
    return [dict(zip(("id", "kind", "status", "created"), row)) for row in rows]


def recover():
    # A restarted process cannot claim a previous provider request is still running.
    with _connect() as con:
        con.execute("UPDATE artifacts SET status='interrupted', payload=? WHERE status='running'", (json.dumps({"error": "Server restarted before this request completed. Start a new run; no live campaign was changed."}),))
