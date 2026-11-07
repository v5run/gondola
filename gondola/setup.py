"""First-run setup: build the demo data and the database if they are missing, then the close history.

    python -m gondola.setup                  # idempotent; the start scripts call it
    python -m gondola.setup --force          # rebuild the database from data/raw
    python -m gondola.setup --skip-history   # data only, no backfill of past closes
    python -m gondola.setup --history        # re-run the history backfill even if it exists

History: the store has used Gondola for a while, so a fresh clone runs the real close for the last 75 nights
(gondola.backfill, ~1-2 minutes; ~3 on a machine with no backtest cache yet). Skipped when out/ already has it.
"""
from __future__ import annotations

import argparse
import sys

from .metrics import ROOT

RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "gondola.duckdb"


def ensure_data(force: bool = False, quiet: bool = False) -> dict:
    did = {"datagen": False, "ingest": False}
    if not (RAW / "pos_orders.csv").exists():
        if not quiet:
            print("Building the demo year (data/raw)...", flush=True)
        from . import datagen
        datagen.main()
        did["datagen"] = True
    if force or not DB.exists():
        if not quiet:
            print("Loading data/raw into data/gondola.duckdb...", flush=True)
        from .connectors.ingest import ingest
        ingest()
        did["ingest"] = True
    (ROOT / "out").mkdir(exist_ok=True)
    return did


def ensure_history(days: int = 75, force: bool = False, quiet: bool = False) -> bool:
    """Backfill past closes if out/ has none (or force). Returns True if it ran."""
    from . import backfill
    if not force and backfill.has_history(ROOT / "out"):
        return False
    if not quiet:
        print(f"Building {days} nights of close history (python -m gondola.backfill --days {days})...", flush=True)
    backfill.run(days, quiet=quiet)
    return True


def ensure_review_history(days: int = 75, quiet: bool = False) -> bool:
    """Tri-workflow: ledger, exceptions, digests and knowledge base for the past nights (gondola.review.history).
    The backfill's closes already run the Review; this only fills nights that have none. Returns True if it ran."""
    from .review import history
    if not quiet:
        print("Checking the ledger / review history...", flush=True)
    return history.ensure(days, quiet=quiet) is not None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--skip-history", action="store_true", help="don't backfill past closes")
    ap.add_argument("--history", action="store_true", help="re-run the history backfill even if it exists")
    ap.add_argument("--history-days", type=int, default=75)
    a = ap.parse_args()
    r = ensure_data(force=a.force)
    print("Data ready." if not any(r.values()) else f"Data ready ({', '.join(k for k, v in r.items() if v)}).")
    if not a.skip_history:
        ran = ensure_history(a.history_days, force=a.history)
        print("History ready." if not ran else "History built.")
        ran = ensure_review_history(a.history_days)
        print("Review history ready." if not ran else "Review history built.")
    sys.exit(0)
