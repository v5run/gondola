"""Fixed tests that the policy-writing agent cannot edit or inspect in advance."""
from __future__ import annotations

from .engine import simulate
from .models import OfferPolicy, RushRequest

TRAINING = [RushRequest(scenario="rush", seed=11), RushRequest(scenario="balanced", seed=19, incident="none"),
            RushRequest(scenario="quiet", seed=29, incident="none")]
# Deliberately different incidents, staffing and traffic from the default UI case.
HELD_OUT = [RushRequest(seed=101, incident="courier_delay"), RushRequest(seed=103, incident="station_outage"),
            RushRequest(scenario="balanced", seed=107, incident="none"),
            RushRequest(scenario="quiet", seed=109, incident="none", budget_cents=300),
            RushRequest(scenario="overload", seed=113, cooks=2), RushRequest(seed=127, cooks=4)]
SEARCH = [OfferPolicy(name="Search: no discount", discount_cents=0), OfferPolicy(name="Search: small offer", discount_cents=50),
          OfferPolicy(name="Search: larger offer", discount_cents=150), OfferPolicy(name="Search: conservative", reserve_minutes=6, max_station_load=0.6),
          OfferPolicy(name="Search: flexible", reserve_minutes=1, load_weight=2), OfferPolicy(name="Search: high reserve", reserve_minutes=9, load_weight=12)]


def evaluate(policy: OfferPolicy, cases: list[RushRequest]) -> dict:
    rows = []
    for req in cases:
        r = simulate(req.model_copy(update={"policy": policy}))
        m = r["metrics"]
        rows.append({"scenario": req.scenario, "seed": req.seed, "incident": req.incident,
                     "metrics": m, "budget_ok": m["promo_spend_cents"] <= req.budget_cents,
                     "accounted_for": m["accepted"] == m["completed"] + m["unresolved"]})
    return {"policy": policy.model_dump(), "cases": rows,
            "mean_score": round(sum(r["metrics"]["service_score"] for r in rows) / len(rows), 2),
            "mean_contribution_cents": round(sum(r["metrics"]["contribution_cents"] for r in rows) / len(rows)),
            "mean_existing_on_time": round(sum(r["metrics"]["existing_on_time"] for r in rows) / len(rows), 2),
            "checks_pass": all(r["budget_ok"] and r["accounted_for"] and not r["metrics"]["unresolved"] for r in rows)}


def qualify(candidate: OfferPolicy) -> dict:
    """No LLM access to this function. Evaluate only after its candidate is fixed."""
    default = evaluate(OfferPolicy(), HELD_OUT)
    proposed = evaluate(candidate, HELD_OUT)
    search_training = [evaluate(p, TRAINING) for p in SEARCH]
    conventional = max(search_training, key=lambda r: r["mean_score"])
    conventional_policy = OfferPolicy.model_validate(conventional["policy"])
    tuned = evaluate(conventional_policy, HELD_OUT)
    preserved = all(p["metrics"]["existing_on_time"] >= b["metrics"]["existing_on_time"] for p, b in zip(proposed["cases"], default["cases"]))
    accepted = proposed["checks_pass"] and preserved and proposed["mean_score"] >= max(default["mean_score"], tuned["mean_score"])
    selected = candidate if accepted else OfferPolicy()
    return {"candidate": proposed, "default": default, "conventional_search": tuned,
            "search_training": search_training, "preserves_each_case": preserved, "qualified": accepted,
            "selected_policy": selected.model_dump(), "selection": "agent_candidate" if accepted else "default_retained",
            "explanation": "Candidate met the fixed held-out score and service gates." if accepted else "Default retained: candidate did not meet every independent score/service gate.",
            "source_mode": "synthetic", "evaluation_scope": "Six held-out modeled cases, not a restaurant pilot"}


def benchmark() -> dict:
    from .engine import MODES
    rows = []
    for req in HELD_OUT:
        rows.append({"scenario": req.scenario, "seed": req.seed, "incident": req.incident,
                     "cooks": req.cooks, "results": {mode: simulate(req, mode)["metrics"] for mode in MODES}})
    return {"source_mode": "synthetic", "cases": rows, "scoring": "Fixed declared service proxy; no real conversion or profit claim"}
