"""The hackathon demo in one command.

    python scripts/run_demo.py

1. Builds the demo data (a year of Hanabi Ramen, Squirrel Hill) and loads it.
2. Taps Close shift for Thu Nov 5, 2026 (rain + Penguins game).
3. Prints the text the manager gets, writes the Daily Close Report PDF, and answers a few Ask questions.
Set TWILIO_ACCOUNT_SID / SENDGRID_API_KEY to send for real; otherwise messages go to out/outbox.jsonl.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gondola import datagen  # noqa: E402
from gondola.connectors.ingest import ingest  # noqa: E402
from gondola.metrics import Store  # noqa: E402
from gondola.pipeline import run_close  # noqa: E402
from gondola.agents.ask import ask  # noqa: E402

if not (ROOT / "data" / "raw" / "pos_orders.csv").exists():
    datagen.main()
ingest()
for sub in ("reports", "forecasts", "bucket"):  # keep eval results; reset only tonight's close state
    shutil.rmtree(ROOT / "out" / sub, ignore_errors=True)
for f in ("closes.json", "outbox.jsonl", "actions_log.jsonl"):
    (ROOT / "out" / f).unlink(missing_ok=True)
r = run_close("2026-11-05", portion_counts={"chashu": 0})  # manager confirms 0 chashu left
print(f"\nClose shift: {r['status']} in {r['seconds']}s")
for s in r["log"]:
    print(f"  {s['step']:9s} {s['status']:7s} {s['seconds']:5.2f}s")
print("\nText to the manager:")
for a in r["alerts"]:
    print("  " + a.get("body", str(a)))
print(f"\nReport: {r['report']['pdf']}")
st = Store()
for q in ["How did we do tonight vs a usual Thursday?", "Why was last Thursday slow?", "DoorDash sales last week?",
          "Which past days were most like tomorrow?", "How good has the forecast been lately?"]:
    print(f"\nQ: {q}\nA: {ask(st, q, '2026-11-05').text}")
