"""Code validation of a proposed knowledge item: recompute the claimed number from the data and reject what can't be
reproduced. The stored number is always the recomputed one; the claim is kept in `validation` for the record.

    event_effect / pricing   effect.change_pct: same weekday with vs without the event/condition (measures.effect)
    item_behavior / capacity effect.value: mean over matching recent days (measures.value): sellout_rate, prep_min,
                             peak_orders_per_hour, orders_per_cook_hour, unavailable_cancels, ...
    ops_rule                 a rule; if it states an effect, that number is validated like the above; otherwise it
                             needs cited evidence dates the store was open
    action_item              owner, check_on, measure{metric, scope, direction, target?}; the baseline is recomputed

Numbers in the statement must also trace to the recomputed (or the within-tolerance claimed) numbers
(agents.guardrails.check_numbers), so wording can't carry an invented figure.
"""
from __future__ import annotations

import pandas as pd

from . import BEHAVIOR_CHANGING, KINDS, MIN_N, confidence_for
from . import measures as M
from ..agents.guardrails import check_numbers

DB = M.DB


def tolerance(metric: str, ref: float, kind: str = "value", n: int | None = None) -> float:
    """How far a claim may be from the recomputed number. Rates over n days move by 1/n per day of new evidence."""
    if kind == "change_pct":
        return max(3.0, 0.25 * abs(ref))
    if metric.endswith("rate") or metric.endswith("pct"):
        return max(0.05, 0.2 * abs(ref), 1.0 / n if n else 0.0)
    return max(0.5, 0.15 * abs(ref))


def same_value(old: dict, new: dict) -> bool:
    """Does `new` re-confirm `old` (same slot) rather than conflict with it?"""
    if old.get("kind") == "action_item":
        return True
    eo, en = old.get("effect") or {}, new.get("effect") or {}
    for key in ("change_pct", "value"):
        if eo.get(key) is not None and en.get(key) is not None:
            n = min(int(old.get("n") or 0), int(new.get("n") or 0)) or None
            return abs(float(eo[key]) - float(en[key])) <= tolerance(eo.get("metric") or "", float(eo[key]), key, n)
    return eo == en


def _reject(reason: str, **kw) -> dict:
    return {"ok": False, "reason": reason, **kw}


def _status(kind: str, n: int, item: dict) -> str:
    if n < MIN_N:
        return "proposed"
    if kind in BEHAVIOR_CHANGING or item.get("changes"):
        return "needs_approval"
    return "active"


def _cited_ok(scope: dict, cited: list, db) -> str | None:
    """Every cited date must be a day the scope describes (open, right weekday, condition present)."""
    if not cited:
        return None
    last = max(str(c)[:10] for c in cited)
    ok = {str(d.date()) for d in M.matching_days(scope, last, 400, db)}
    bad = [c for c in cited if str(c)[:10] not in ok]
    return f"cited dates don't match the scope: {', '.join(map(str, bad[:3]))}" if bad else None


def validate(item: dict, as_of: str | None = None, db=DB, led=None) -> dict:
    """Returns {ok, reason, item (normalized, numbers recomputed, n, evidence, confidence, status), recomputed, claimed,
    n, tolerance}."""
    kind = item.get("kind")
    if kind not in KINDS:
        return _reject(f"unknown kind '{kind}'")
    if not str(item.get("statement") or "").strip():
        return _reject("statement is required")
    as_of = str(pd.Timestamp(as_of or M.data(db)["days"].date.max()).date())
    scope = dict(item.get("scope") or {})
    eff = dict(item.get("effect") or {})
    out = {k: v for k, v in item.items() if k not in ("status", "validation", "rejected_reason")}
    out["scope"] = scope

    if kind == "action_item":
        return _validate_action(out, as_of, db, led)

    metric = eff.get("metric")
    if kind == "ops_rule" and not metric:
        cited = item.get("evidence") or []
        if len(cited) < 1:
            return _reject("an ops_rule without a measured effect must cite evidence dates")
        bad = _cited_ok({k: v for k, v in scope.items() if k in ("weekday",)}, cited, db)
        if bad:
            return _reject(bad)
        g = check_numbers(item["statement"], [{"n": len(cited)}])
        if not g["ok"]:
            return _reject(f"statement has numbers with no source: {g['unsupported']}", claimed=None)
        n = len(cited)
        out.update(n=n, evidence=sorted(map(str, cited))[-12:], confidence=confidence_for(n), base_confidence=confidence_for(n),
                   last_confirmed=as_of, status=_status(kind, n, item),
                   validation={"as_of": as_of, "method": "cited evidence only"})
        return {"ok": True, "reason": None, "item": out, "recomputed": None, "claimed": None, "n": n, "status": out["status"]}

    if not metric:
        return _reject("effect.metric is required")
    use_change = eff.get("change_pct") is not None
    if kind in ("event_effect", "pricing") and not use_change:
        return _reject(f"{kind} needs effect.change_pct")
    if not use_change and eff.get("value") is None:
        return _reject("effect needs change_pct or value")
    try:
        claimed = float(eff["change_pct"] if use_change else eff["value"])
    except (TypeError, ValueError):
        return _reject("effect number is not numeric")
    try:
        if use_change:
            r = M.effect(metric, scope, eff, as_of, db, led=led)
            rec = r.get("change_pct")
        else:
            r = M.value(metric, scope, eff, as_of, db, led=led)
            rec = r.get("value")
    except KeyError as e:
        return _reject(str(e).strip("'\""))
    if r.get("error"):
        return _reject(r["error"])
    if rec is None or not r.get("n"):
        return _reject("can't reproduce: no matching days in the data", claimed=claimed)
    key = "change_pct" if use_change else "value"
    tol = tolerance(metric, rec, key, int(r.get("n") or 0) or None)
    if abs(claimed - rec) > tol:
        return _reject(f"claimed {claimed:g} but the data gives {rec:g} (tolerance {tol:.2g})", claimed=claimed, recomputed=rec,
                       n=r["n"], tolerance=round(tol, 3))
    bad = _cited_ok(scope, item.get("evidence") or [], db)
    if bad:
        return _reject(bad, claimed=claimed, recomputed=rec)
    g = check_numbers(item["statement"], [{"v": rec, "claimed": claimed, "n": r["n"], "per_day": r.get("per_day")}])
    if not g["ok"]:
        return _reject(f"statement has numbers the data doesn't support: {g['unsupported']}", claimed=claimed, recomputed=rec)
    n = int(r["n"])
    conf = confidence_for(n, r.get("agreement"))
    out["effect"] = {**eff, key: rec}
    out.update(n=n, evidence=r["evidence"][-12:], confidence=conf, base_confidence=conf, last_confirmed=as_of,
               status=_status(kind, n, item),
               validation={"as_of": as_of, "claimed": claimed, "recomputed": rec, "tolerance": round(tol, 3),
                           "method": "same weekday with vs without" if use_change else "mean over matching days",
                           "agreement": r.get("agreement")})
    if n < MIN_N:
        out["estimate"] = True
    return {"ok": True, "reason": None, "item": out, "recomputed": rec, "claimed": claimed, "n": n,
            "tolerance": round(tol, 3), "status": out["status"]}


def _validate_action(out: dict, as_of: str, db, led) -> dict:
    if not out.get("owner"):
        return _reject("action_item needs an owner")
    try:
        check_on = str(pd.Timestamp(out.get("check_on")).date())
    except Exception:  # noqa: BLE001
        return _reject("action_item needs a check_on date")
    if check_on <= as_of:
        return _reject("check_on must be after today")
    meas = dict(out.get("measure") or {})
    metric = meas.get("metric")
    if not metric:
        return _reject("action_item needs measure.metric (or 'manual')")
    if metric != "manual":
        win = int(meas.get("window_days") or 14)
        r = M.value(metric, meas.get("scope") or {}, None, as_of, db, lookback=win, led=led)
        if r.get("error"):
            return _reject(r["error"])
        if r["value"] is None:
            return _reject(f"can't compute a baseline for {metric}")
        if meas.get("baseline") is not None and abs(float(meas["baseline"]) - r["value"]) > tolerance(metric, r["value"]):
            return _reject(f"claimed baseline {meas['baseline']} but the data gives {r['value']}", claimed=meas["baseline"],
                           recomputed=r["value"])
        meas.update(baseline=r["value"], baseline_n=r["n"], window_days=win, direction=meas.get("direction") or "down")
        facts = [{"baseline": r["value"], "target": meas.get("target")}]
    else:
        facts = []
    facts.append(out.get("params") or {})  # chosen parameters (e.g. a pause threshold) are settings, not data claims
    g = check_numbers(out["statement"], facts)
    if not g["ok"]:
        return _reject(f"statement has numbers with no source: {g['unsupported']}")
    out.update(measure=meas, check_on=check_on, n=int(meas.get("baseline_n") or 0), evidence=out.get("evidence") or [as_of],
               confidence=None, last_confirmed=as_of, status="active", action_status="open",
               validation={"as_of": as_of, "baseline": meas.get("baseline")})
    return {"ok": True, "reason": None, "item": out, "recomputed": meas.get("baseline"), "claimed": None,
            "n": out["n"], "status": "active"}
