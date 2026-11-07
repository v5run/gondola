"""Reproduce the fixed synthetic comparison. No model key or network required."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gondola.rush.engine import compare
from gondola.rush.evaluation import benchmark
from gondola.rush.models import RushRequest

root = Path(__file__).resolve().parents[1]
out = root / "docs" / "demo"
out.mkdir(parents=True, exist_ok=True)
default = compare(RushRequest(forecast_pressure=1.15))
results = benchmark()
summary = {}
for mode in default["runs"]:
    rows = [c["results"][mode] for c in results["cases"]]
    summary[mode] = {"mean_contribution_cents": round(sum(m["contribution_cents"] for m in rows) / len(rows)),
                     "mean_case_handoff_wait_minutes": round(sum(m["avg_wait_minutes"] for m in rows) / len(rows), 2),
                     "existing_promises_met": sum(m["existing_on_time"] for m in rows),
                     "existing_promises": sum(m["existing_orders"] for m in rows),
                     "unresolved": sum(m["unresolved"] for m in rows)}
evidence = {"measured_at": datetime.now(timezone.utc).isoformat(), "source_mode": "synthetic",
            "default_request": default["request"], "default": {k: r["metrics"] for k, r in default["runs"].items()},
            "held_out_summary": summary, "held_out": results,
            "limits": "Small designed simulator, not merchant/conversion/ROI evidence. Unweighted case means. Controller sees estimates; evaluator alone sees physical truth. Fixed task noise and buyer utilities across controllers."}
(out / "evaluation.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
