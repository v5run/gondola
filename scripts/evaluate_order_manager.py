"""Evaluate admission mechanics with explicit quote/decline accounting, offline.

This is a declared-duration simulation, not held-out restaurant/LLM evidence.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gondola.orders import engine, service
from gondola.orders.models import Session


def metrics(state):
    completed = [o for o in state.orders if o.status == "completed"]
    return {"observed": len(state.orders), "completed": len(completed),
            "unfinished": sum(o.status == "accepted" for o in state.orders),
            "declined": sum(o.status == "declined" for o in state.orders),
            "expired": sum(o.status == "expired" for o in state.orders),
            "accepted_later": sum(o.decision == "accept_later" for o in state.orders),
            "quote_extension_minutes": sum(o.promise - o.request.requested_ready_minute for o in completed),
            "missed_agreed_promises": sum(o.tasks[-1].end > o.promise for o in completed),
            "missed_original_requested_times": sum(o.tasks[-1].end > o.request.requested_ready_minute for o in completed),
            "total_lateness_against_agreed_promises": sum(max(0, o.tasks[-1].end - o.promise) for o in completed),
            "by_channel": {channel: {"observed": sum(o.request.channel == channel for o in state.orders),
                                      "completed": sum(o.request.channel == channel for o in completed),
                                      "declined": sum(o.request.channel == channel and o.status == "declined" for o in state.orders)}
                           for channel in ("doordash", "ubereats", "dine_in", "pickup")}}


def evaluate():
    cases = []
    for cooks in (1, 2, 3, 4):
        for speed in (1, .5):
            state = Session(policy={"cooks": cooks}); state.speeds["fryer"] = speed
            engine.receive(state, service.demo_orders())
            baseline = state.model_copy(deep=True)
            for order in baseline.orders:
                if order.status == "pending":
                    engine.commit_order(baseline, order, order.request.requested_ready_minute, "blind_accept_requested")
            engine.advance(baseline, 120)
            result = {"cooks": cooks, "fryer_speed": speed, "blind_forwarding": metrics(baseline), "checked_priorities": {}}
            for strategy in engine.STRATEGIES:
                proposal, candidate = engine.proposal(state, strategy)
                if not proposal["allowed"]:
                    result["checked_priorities"][strategy] = {"blocked": True, "reason": proposal["reason"]}
                    continue
                engine.advance(candidate, 120)
                result["checked_priorities"][strategy] = metrics(candidate)
            cases.append(result)
    return {"source_mode": "synthetic_declared_duration_simulation", "model_calls": 0, "cases": cases,
            "limits": "Both admission and simulated progress use declared recipe work and observed speed. This tests reservation/accounting mechanics. Later promises require explicit fixture authorization; extensions and declines are retained, so on-time rates must not be compared without those counts. No real merchant, held-out duration or LLM-quality result is established."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(next(c for c in result["cases"] if c["cooks"] == 3 and c["fryer_speed"] == 1), indent=2))
