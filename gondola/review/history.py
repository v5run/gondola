"""Review history for the demo: the store has run Gondola for a while, so the ledger, the digests and the knowledge base
have a past. Replays each closed night in order, exactly as the close would have run it that night (measures and
validation only read data up to that night; exceptions are recorded but never texted).

    python -m gondola.review.history --days 75            # ledger + exceptions + review for the last 75 closed nights
    python -m gondola.review.history --days 75 --reset    # wipe the knowledge base / digests / review events first

The history backfill (gondola/backfill.py) already runs the Review as the last step of every past close; `ensure`
(called by gondola/setup.py) only fills nights that have no review yet.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

from ..kb import kb as _kb
from ..ledger import ledger
from ..ledger.build import DB, build_day
from . import digests as D


def nights(days: int, end: str | None = None, db: Path | str = DB) -> list[str]:
    from .. import now as clock
    info = clock.info(db)
    last = end or (info["today"] if info["phase"] == "closed" else
                   str((pd.Timestamp(info["today"]) - pd.Timedelta(days=1)).date()))
    return [str(d.date()) for d in pd.date_range(pd.Timestamp(last) - pd.Timedelta(days=days - 1), last)]


def build(days: int = 75, end: str | None = None, db: Path | str = DB, reset: bool = False, quiet: bool = True,
          only_missing: bool = False) -> dict:
    from .agent import run_review
    led, kb, dg = ledger(), _kb(), D.digests()
    if reset:
        kb.clear()
        dg.clear()
        with led._con() as c:  # review-written events are rebuilt; order/books events stay (idempotent anyway)
            c.execute("DELETE FROM events WHERE source = 'review'")
    have = set(dg.review_dates()) if only_missing else set()
    todo = [d for d in nights(days, end, db) if d not in have]
    t0, rows = time.perf_counter(), []
    for d in todo:
        t = time.perf_counter()
        build_day(d, db, led)
        r = run_review(d, db=db, led=led, kb=kb, dg=dg, model=False, send=False)
        rows.append({"date": d, "wrong": len(r["wrong"]), "actions": len(r["actions"]),
                     "kb": sum(1 for c in r["kb_changes"] if c["op"] in ("add", "supersede")), "s": round(time.perf_counter() - t, 2)})
        if not quiet:
            print(f"  {d}  wrong {rows[-1]['wrong']}  actions {rows[-1]['actions']}  kb+ {rows[-1]['kb']}  {rows[-1]['s']}s", flush=True)
    status: dict[str, int] = {}
    for it in kb.list():
        status[it["status"]] = status.get(it["status"], 0) + 1
    return {"nights": len(todo), "first": todo[0] if todo else None, "last": todo[-1] if todo else None,
            "seconds": round(time.perf_counter() - t0, 1), "kb_status": status,
            "digests": {k: len(dg.list(k)) for k in ("day", "week", "month")}}


def ensure(days: int = 75, db: Path | str = DB, quiet: bool = True) -> dict | None:
    """Fill nights without a review (no-op when the backfill already ran the Review in each close)."""
    have = set(D.digests().review_dates())
    want = nights(days, None, db)
    if all(d in have for d in want):
        return None
    return build(days, None, db, only_missing=True, quiet=quiet)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build ledger, exceptions, digests and knowledge base history.")
    ap.add_argument("--days", type=int, default=75)
    ap.add_argument("--end", default=None)
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(build(a.days, a.end, reset=a.reset, quiet=a.quiet), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
