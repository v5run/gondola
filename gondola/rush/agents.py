"""Real, bounded tool use: the model chooses actions/policies; code enforces authority."""
from __future__ import annotations

import asyncio
import json
from typing import Callable

from .engine import MENU, compare, snapshot
from .evaluation import TRAINING, evaluate, qualify
from .models import AgentRequest, OfferPolicy


async def _run(name: str, instruction: str, tools: list, progress: Callable, message: str):
    from google.adk.agents import LlmAgent
    from ..agents.adk_graph import configured_model, run_agent
    model = configured_model()
    if model is None:
        raise ValueError("Live agent mode is not configured. Offline comparisons remain available.")
    usage = []

    def capture(callback_context, llm_response):
        meta = getattr(llm_response, "usage_metadata", None)
        if meta:
            usage.append(meta.model_dump(mode="json"))
        return None

    agent = LlmAgent(name=name, model=model, instruction=instruction, tools=tools, after_model_callback=capture)
    def event(kind, data):
        progress({"kind": kind, **data})
    result = await asyncio.wait_for(run_agent(agent, {}, message, event, max_llm_calls=12), timeout=110)
    return {"model": str(model), "tool_calls": result["tool_calls"], "usage": usage, "invoked": result["invoked"]}


async def controller(req: AgentRequest, progress: Callable) -> dict:
    kitchen = snapshot(req, req.minute)
    trace: list[dict] = []
    receipts: list[dict] = []

    def record(tool: str, args: dict, result: dict):
        if len(trace) >= 14:
            raise ValueError("Tool budget exhausted")
        trace.append({"tool": tool, "args": args, "result": result})
        progress({"kind": "tool", "tool": tool, "args": args, "result": result})
        return result

    def inspect_kitchen() -> dict:
        """Read current observed orders, resources, inventory, forecast, and remaining budget. No future outcomes."""
        obs = kitchen.observe()
        # Compact enough for a live demo, but preserve exact public facts.
        obs["orders"] = [{k: o[k] for k in ("id", "item", "channel", "promise", "eta", "ready")} for o in obs["orders"] if o["ready"] is None]
        obs["menu"] = MENU
        return record("inspect_kitchen", {}, obs)

    def compare_approved_offers() -> dict:
        """Evaluate all approved items against the same accepted-work reservations and owner limits."""
        return record("compare_approved_offers", {}, {"offers": kitchen.offers()})

    def check_offer(item_id: str, discount_cents: int) -> dict:
        """Check a proposed item and integer discount in cents without publishing. Fixed maximum discount is 200 cents."""
        return record("check_offer", {"item_id": item_id, "discount_cents": discount_cents}, kitchen.evaluate_offer(item_id, discount_cents))

    def publish_simulated_offer(item_id: str, discount_cents: int) -> dict:
        """Apply one checked five-minute offer to the simulated first-party menu. A rejection is not a success."""
        if receipts:
            return record("publish_simulated_offer", {}, {"status": "rejected", "reason": "One applied intervention per agent request"})
        receipt = kitchen.publish_offer(item_id, discount_cents, source="gemini")
        if receipt["status"] == "applied":
            receipts.append(receipt)
        return record("publish_simulated_offer", {"item_id": item_id, "discount_cents": discount_cents}, receipt)

    def pause_simulated_offers() -> dict:
        """Apply a no-offer decision if available interventions are unsafe or unattractive."""
        if receipts:
            return {"status": "rejected", "reason": "An intervention was already applied"}
        receipt = kitchen.publish_offer(None, source="gemini")
        receipts.append(receipt)
        return record("pause_simulated_offers", {}, receipt)

    meta = await _run("rush_controller", "You manage a simulated restaurant's first-party offers. Inspect the kitchen and compare offers before acting. "
                     "Choose one feasible item/discount or pause. Preserve accepted promises, budget and stock. "
                     "You can feature without discount (zero cents). A tool rejection is not success. "
                     "Only tools apply actions; do not invent results or call external services. Stop after one applied receipt. "
                     "The world and buyer response are synthetic; do not claim real conversion or DoorDash publication.",
                     [inspect_kitchen, compare_approved_offers, check_offer, publish_simulated_offer, pause_simulated_offers], progress,
                     "Inspect the current observations, decide what we should feature now, and apply one supported simulated intervention.")
    if not receipts:
        raise ValueError("The model did not complete an applied tool intervention. No successful agent action is claimed.")
    receipt = receipts[-1]
    forced = {"item": receipt.get("item"), "discount_cents": receipt.get("discount_cents", 0)}
    comparison = compare(req, forced=forced, at=req.minute)
    applied = [a for a in comparison["runs"]["coordinated"]["actions"] if a.get("source") == "gemini" and a["minute"] == req.minute]
    if not applied:
        raise ValueError("Replay did not confirm the requested intervention; no verified result is claimed.")
    return {"agent_mode": "live_model", "data_mode": "synthetic", "campaign_mode": "simulation",
            **meta, "trace": trace, "receipt": applied[-1], "comparison": comparison}


async def policy_lab(objective: str, progress: Callable) -> dict:
    trials: list[dict] = []
    submitted: list[OfferPolicy] = []

    def training_brief() -> dict:
        """Read the fixed development-case description and default policy's development results only."""
        result = {"cases": [{"scenario": r.scenario, "incident": r.incident, "cooks": r.cooks} for r in TRAINING],
                  "baseline": evaluate(OfferPolicy(), TRAINING), "maximum_tests": 6,
                  "objective": "Fixed score = modeled contribution minus 0.60 per late minute and 0.08 per holding minute. Preserve existing-order service. Held-out cases are unavailable."}
        progress({"kind": "tool", "tool": "training_brief", "result": result})
        return result

    def test_policy(name: str, load_weight: float, minimum_margin_cents: int, reserve_minutes: int,
                    discount_cents: int, max_station_load: float) -> dict:
        """Evaluate a bounded offer policy on development cases. Does not expose held-out data or change the scorer."""
        if len(trials) >= 6:
            return {"status": "rejected", "reason": "Six-candidate development budget exhausted"}
        try:
            policy = OfferPolicy(name=name, load_weight=load_weight, minimum_margin_cents=minimum_margin_cents,
                                 reserve_minutes=reserve_minutes, discount_cents=discount_cents, max_station_load=max_station_load)
        except Exception:
            return {"status": "rejected", "reason": "Policy outside the allowed parameter bounds"}
        values = policy.model_dump(exclude={"name"})
        if any(t["policy"]["name"] == name or {k: v for k, v in t["policy"].items() if k != "name"} == values for t in trials):
            return {"status": "rejected", "reason": "Use a unique name and genuinely different policy parameters"}
        result = evaluate(policy, TRAINING)
        trials.append(result)
        progress({"kind": "tool", "tool": "test_policy", "result": result})
        return result

    def submit_policy(name: str) -> dict:
        """Submit a previously tested policy by its exact name for independent qualification after this agent stops."""
        match = next((t for t in trials if t["policy"]["name"] == name), None)
        if match is None:
            return {"status": "rejected", "reason": "Test the exact policy before submitting it"}
        submitted[:] = [OfferPolicy.model_validate(match["policy"])]
        progress({"kind": "tool", "tool": "submit_policy", "result": {"status": "submitted", "name": name}})
        return {"status": "submitted", "name": name}

    meta = await _run("policy_researcher", "Develop an inspectable offer policy for a synthetic kitchen. "
                     "Read training_brief. Test between two and six different policies, inspect feedback and revise. "
                     "Use actual tool results, then submit the best tested policy by name. You cannot edit evaluator, world, safety guards or access held-out outcomes. "
                     "A simple conventional six-policy search is a comparator. We keep the default unless the independent score/service gates pass. "
                     "Do not promise improvement or claim restaurant performance. Stop after submission.",
                     [training_brief, test_policy, submit_policy], progress, objective)
    if not submitted or len(trials) < 2:
        raise ValueError("The agent did not finish at least two actual tests and submit a policy.")
    progress({"kind": "evaluation", "status": "running", "text": "Agent stopped. Evaluating fixed held-out cases and conventional search."})
    qualification = qualify(submitted[0])
    return {"agent_mode": "live_model", "data_mode": "synthetic", **meta,
            "trials": trials, "qualification": qualification, "proposed_policy": submitted[0].model_dump(),
            "scope": "Agent-generated bounded policy parameters, not arbitrary code invention or model fine-tuning"}
