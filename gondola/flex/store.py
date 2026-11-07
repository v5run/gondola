from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / ".local" / "flex-pickup.sqlite3"


@contextmanager
def transaction():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=20)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def read(con, ident: str) -> dict:
    row = con.execute("SELECT payload FROM sessions WHERE id=?", (ident,)).fetchone()
    if row is None: raise KeyError("Unknown checkout session")
    return json.loads(row[0])


def save(con, session: dict):
    con.execute("INSERT INTO sessions VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (session["id"], json.dumps(session)))
