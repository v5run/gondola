"""Exceptions agent: watches the ledger during the day and decides what needs attention now.

Triggers (code, over the ledger, as of `now`):
  late_orders       orders past due by more than 10 minutes (needs Present's promise / courier ETA / handed_off.late_min)
  cancel_cluster    3+ cancellations or refunds within 30 minutes
  payout_issue      an app payout report lands with error charges or a shortfall over $1
  station_incident  a station incident / slowdown lasting more than 15 minutes (action.applied or incident.* events)
  forecast_miss     by mid-service, orders so far are outside the day forecast's range for that time
For each new trigger the agent gathers evidence with tools and decides: alert (Sentinel text, bundled, quiet hours,
dedupe), present (hand to Present, e.g. pause an item on Grubhub) or note (for the close review). It writes
`exception.raised` into the ledger. With a model configured the decision and note come from the LLM (numbers checked);
offline, deterministic rules make the same structured decision.
"""
from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timedelta
from functools import lru_cache

import pandas as pd

from ..agents.guardrails import check_numbers
from ..ledger import Event, Ledger, ledger
from ..ledger.summary import per_order
from ..metrics import ROOT

DB = ROOT / "data" / "gondola.duckdb"
LATE_MIN = 10
CLUSTER_N, CLUSTER_WINDOW_MIN = 3, 30
INCIDENT_MIN = 15
PAYOUT_SHORT_USD = 10  # smaller gaps are rounding/adjustment noise; Books still lists them
DECISIONS = ("alert", "present", "note")
INCIDENT_ACTIONS = {"incident", "slowdown", "station_down", "station_slow"}


def _t(ts: str) -> datetime:
    return datetime.fromisoformat(ts[:19])


def _hm(ts: str) -> str:
    return ts[11:16]


def _due(date: str, p: dict) -> datetime | None:
    hm = p.get("promise") or p.get("courier_eta")
    if not hm:
        return None
    try:
        d = datetime.fromisoformat(f"{date}T{hm[:5]}:00")
    except ValueError:
        return None
    return d + timedelta(days=1) if hm[:2] < "04" else d


@lru_cache(maxsize=4)
def _chashu_items(db: str) -> frozenset:
    """Menu items that use the limited item (chashu)."""
    import duckdb
    con = duckdb.connect(db, read_only=True)
    try:
        return frozenset(r[0] for r in con.execute("SELECT item FROM menu WHERE chashu_portions > 0").fetchall())
    finally:
        con.close()


# ------------------------------------------------------------------ triggers
def trig_late(date: str, evs: list[Event], now: datetime) -> list[dict]:
    po = per_order(evs)
    late = []
    for oid, t in po.items():
        if "order.cancelled" in t:
            continue
        h = t.get("order.handed_off")
        if h is not None and h.payload.get("late_min") is not None:
            if float(h.payload["late_min"]) > LATE_MIN:
                rec = t.get("order.received")
                late.append({"order_id": oid, "late_min": round(float(h.payload["late_min"]), 1), "ts": h.ts,
                             "channel": h.payload.get("channel") or (rec.payload.get("channel") if rec else None)})
            continue
        rec = t.get("order.received")
        if rec is None or h is not None:
            continue
        due = _due(date, rec.payload)
        if due and now > due + timedelta(minutes=LATE_MIN):
            late.append({"order_id": oid, "late_min": round((now - due).total_seconds() / 60, 1), "ts": now.isoformat(timespec="seconds"),
                         "channel": rec.payload.get("channel"), "open": True})
    out: dict[str, list] = {}
    for x in late:
        b = x["ts"][11:13] + (":00" if x["ts"][14:16] < "30" else ":30")
        out.setdefault(b, []).append(x)
    res = []
    for b, xs in sorted(out.items()):
        worst = max(x["late_min"] for x in xs)
        res.append({"id": f"{date}:late:{b.replace(':', '')}", "kind": "late_orders", "ts": max(x["ts"] for x in xs)[:19],
                    "severity": "high" if len(xs) >= 3 or worst >= 20 else "medium",
                    "title": f"{len(xs)} order{'s' if len(xs) != 1 else ''} more than {LATE_MIN} min past due ({b})",
                    "evidence": {"orders": len(xs), "worst_late_min": worst, "order_ids": [x["order_id"] for x in xs][:10],
                                 "channels": sorted({x["channel"] for x in xs if x.get("channel")})}})
    return res


def trig_cancels(date: str, evs: list[Event], now: datetime, db=DB) -> list[dict]:
    cs = sorted([e for e in evs if e.type in ("order.cancelled", "order.refunded")], key=lambda e: e.ts)
    seen_orders: set = set()
    cs = [e for e in cs if not (e.payload.get("order_id") in seen_orders or seen_orders.add(e.payload.get("order_id")))]
    res, used = [], set()
    for i, e in enumerate(cs):
        if i in used:
            continue
        end = _t(e.ts) + timedelta(minutes=CLUSTER_WINDOW_MIN)
        grp = [j for j in range(i, len(cs)) if _t(cs[j].ts) <= end and j not in used]
        if len(grp) < CLUSTER_N:
            continue
        # extend: keep absorbing cancels within the window of the last one (one exception per burst)
        k = grp[-1]
        while k + 1 < len(cs) and _t(cs[k + 1].ts) <= _t(cs[k].ts) + timedelta(minutes=CLUSTER_WINDOW_MIN):
            k += 1
            grp.append(k)
        used.update(grp)
        g = [cs[j] for j in grp]
        reasons: dict[str, int] = {}
        items: dict[str, int] = {}
        chans: dict[str, int] = {}
        for x in g:
            r = x.payload.get("reason") or "unknown"
            reasons[r] = reasons.get(r, 0) + 1
            ch = x.payload.get("channel") or "unknown"
            chans[ch] = chans.get(ch, 0) + 1
            for it in x.payload.get("items") or []:
                items[it] = items.get(it, 0) + 1
        top_reason = max(reasons.items(), key=lambda x: x[1])[0]
        try:
            ch_items = _chashu_items(str(db))
        except Exception:  # noqa: BLE001
            ch_items = frozenset()
        with_chashu = sum(1 for x in g if ch_items & set(x.payload.get("items") or []))
        amount = round(sum(float(x.payload.get("amount") or 0) for x in g), 2)
        res.append({"id": f"{date}:cancels:{_hm(e.ts).replace(':', '')}", "kind": "cancel_cluster", "ts": g[-1].ts[:19],
                    "severity": "high" if len(g) >= 5 else "medium",
                    "title": f"{len(g)} cancellations {_hm(g[0].ts)}–{_hm(g[-1].ts)} ({top_reason.replace('_', ' ')})",
                    "evidence": {"cancels": len(g), "first": _hm(g[0].ts), "last": _hm(g[-1].ts), "reasons": reasons,
                                 "by_channel": chans, "amount": amount, "with_chashu": with_chashu,
                                 "top_items": dict(sorted(items.items(), key=lambda x: -x[1])[:4]),
                                 "order_ids": [x.payload.get("order_id") for x in g][:10]}})
    return res


def trig_payouts(date: str, evs: list[Event], now: datetime) -> list[dict]:
    res = []
    for e in evs:
        if e.type != "payout.report_arrived":
            continue
        p = e.payload
        diff = p.get("difference")
        if not ((diff is not None and diff < -PAYOUT_SHORT_USD) or (p.get("recoverable_usd") or 0) >= PAYOUT_SHORT_USD):
            continue
        rec = float(p.get("recoverable_usd") or 0)
        res.append({"id": f"{date}:payout:{p.get('for_date')}:{p.get('channel')}", "kind": "payout_issue", "ts": e.ts[:19],
                    "severity": "high" if rec >= 75 else "low",
                    "title": f"{p.get('channel')} report for {p.get('for_date')}: {p.get('error_charges', 0)} error charges, "
                             f"${-(diff or 0):,.2f} short",
                    "evidence": {k: p.get(k) for k in ("for_date", "channel", "difference", "error_charges", "error_charge_usd",
                                                       "recoverable_usd", "n_disputable", "missing_orders")}})
    return res


def trig_incidents(date: str, evs: list[Event], now: datetime) -> list[dict]:
    open_: dict[str, Event] = {}
    spans = []
    for e in evs:
        p = e.payload
        st = p.get("station") or p.get("item") or "kitchen"
        start = (e.type == "incident.started") or (e.type == "action.applied" and p.get("action") in INCIDENT_ACTIONS)
        stop = (e.type in ("incident.ended", "incident.resolved")) or (
            e.type == "action.applied" and p.get("action") in ("resume", "recovered", "incident_end") and st in open_)
        if start and st not in open_:
            open_[st] = e
        elif stop and st in open_:
            s = open_.pop(st)
            spans.append((st, s, e.ts))
    for st, s in open_.items():
        spans.append((st, s, None))
    res = []
    for st, s, end in spans:
        mins = ((_t(end) if end else now) - _t(s.ts)).total_seconds() / 60
        if mins <= INCIDENT_MIN:
            continue
        res.append({"id": f"{date}:incident:{st}:{_hm(s.ts).replace(':', '')}", "kind": "station_incident",
                    "ts": (end or now.isoformat(timespec="seconds"))[:19],
                    "severity": "high" if mins >= 30 or end is None else "medium",
                    "title": f"{st} incident since {_hm(s.ts)}" + (f", {mins:.0f} min" if end else f", still open after {mins:.0f} min"),
                    "evidence": {"station": st, "start": _hm(s.ts), "end": _hm(end) if end else None, "minutes": round(mins, 1),
                                 "speed": s.payload.get("value") or s.payload.get("speed"), "reason": s.payload.get("reason")}})
    return res


def mid_service(date: str) -> datetime:
    from ..now import OPEN_MIN, close_min
    m = (OPEN_MIN + close_min(date)) // 2
    return datetime.fromisoformat(date) + timedelta(minutes=m)


def trig_forecast(date: str, evs: list[Event], now: datetime, db=DB) -> list[dict]:
    mid = mid_service(date)
    if now < mid:
        return []
    fcs = [e for e in evs if e.type == "forecast.issued" and (e.payload.get("horizon") == "day") and e.ts <= mid.isoformat()]
    if not fcs:
        return []
    t = fcs[-1].payload.get("total") or {}
    if not t.get("p50"):
        return []
    from ..kb import measures as M
    bins = M.data(db)["bins"]
    d0 = pd.Timestamp(date)
    prev = sorted({d for d in bins.date.unique() if d < d0 and pd.Timestamp(d).dayofweek == d0.dayofweek})[-4:]
    slot = mid.hour * 4 + mid.minute // 15
    b = bins[bins.date.isin(prev)]
    tot = b.orders.sum() + b.cancels.sum()
    share = float((b[b.slot < slot].orders.sum() + b[b.slot < slot].cancels.sum()) / tot) if tot else None
    if not share:
        return []
    got = len({e.payload.get("order_id") for e in evs if e.type == "order.received" and e.ts < mid.isoformat()})
    lo, mid50, hi = (round(float(t[k]) * share, 1) for k in ("p10", "p50", "p90"))
    if lo <= got <= hi:
        return []
    side = "above" if got > hi else "below"
    pct = round((got / mid50 - 1) * 100, 1) if mid50 else None
    return [{"id": f"{date}:forecast_miss", "kind": "forecast_miss", "ts": mid.isoformat(timespec="seconds"),
             "severity": "medium" if abs(pct or 0) < 20 else "high",
             "title": f"Orders by {mid:%H:%M} are {side} the forecast range ({got} vs {lo}–{hi})",
             "evidence": {"by": f"{mid:%H:%M}", "orders_so_far": got, "expected_p10": lo, "expected_p50": mid50, "expected_p90": hi,
                          "vs_p50_pct": pct, "share_of_day": round(share, 3), "side": side}}]


TRIGGERS = [trig_late, trig_payouts, trig_incidents]


def candidates(date: str, now: datetime, led: Ledger, db=DB) -> list[dict]:
    end = now.isoformat(timespec="seconds")
    evs = [e for e in led.query(date) if e.ts <= end]
    out = []
    for f in TRIGGERS:
        out += f(date, evs, now)
    out += trig_cancels(date, evs, now, db)
    out += trig_forecast(date, evs, now, db)
    return out


# ------------------------------------------------------------------ deciding
def decide_offline(c: dict, kb_rules: list | None = None) -> dict:
    """Ranked deterministic rules: the same structured output the LLM gives."""
    k, ev = c["kind"], c["evidence"]
    if k == "late_orders":
        dec = "alert" if ev["orders"] >= 5 else "present"
        note = (f"{ev['orders']} orders past due, worst {ev['worst_late_min']} min late. "
                "Present should quote longer prep times on the delivery apps until the queue clears.")
    elif k == "cancel_cluster":
        reason = max(ev["reasons"].items(), key=lambda x: x[1])[0]
        item = next(iter(ev["top_items"]), None)
        if reason == "item_unavailable":
            dec = "alert" if ev["cancels"] >= 5 else "present"
            what = "chashu" if ev.get("with_chashu", 0) * 2 >= ev["cancels"] else (item or "the item")
            note = (f"{ev['cancels']} cancellations for unavailable items {ev['first']}–{ev['last']}"
                    + (f" ({ev['with_chashu']} with chashu dishes)" if ev.get("with_chashu") else "")
                    + f". Present should pause {what} on the delivery apps; the manager should recount.")
        else:
            dec = "note"
            note = f"{ev['cancels']} cancellations {ev['first']}–{ev['last']} ({reason.replace('_', ' ')}); noted for the close review."
    elif k == "payout_issue":
        dec = "note"
        rec = ev.get("recoverable_usd") or 0
        note = (f"{ev['channel']} paid ${-(ev.get('difference') or 0):,.2f} less than expected for {ev['for_date']}"
                + (f"; ${rec:,.2f} looks recoverable ({ev.get('n_disputable', 0)} disputable charges)" if rec else "")
                + ". Books adds the dispute checklist at close.")
    elif k == "station_incident":
        dec = "alert"
        note = (f"{ev['station']} incident from {ev['start']}" + (f" to {ev['end']}" if ev.get("end") else ", still open")
                + f" ({ev['minutes']} min). Check the station; Present is already padding its times.")
    elif k == "forecast_miss":
        dec = "present"
        note = (f"{ev['orders_so_far']} orders by {ev['by']}, {ev['side']} the expected {ev['expected_p10']}–{ev['expected_p90']}. "
                "Future's nowcast and Present's reservations should follow the actual pace.")
    else:
        dec, note = "note", c.get("title", k)
    if kb_rules:
        note += " Rule on file: " + kb_rules[0].get("statement", "")
    return {"decision": dec, "note": note, "by": "rules"}


def decide_llm(cands: list[dict], model, date: str, led: Ledger) -> dict[str, dict]:
    """One Exceptions-agent call for all new triggers. Returns {id: {decision, note, by}} for the ones it decided
    with checked numbers; anything else falls back to the rules."""
    from . import llm
    from ..kb import kb as _kb
    by_id = {c["id"]: c for c in cands}

    def get_trigger(exception_id: str) -> dict:
        """The trigger's evidence (counts, times, order ids)."""
        c = by_id.get(exception_id)
        return {k: c[k] for k in ("id", "kind", "severity", "title", "evidence")} if c else {"error": "unknown id"}

    def get_orders(start: str, end: str) -> list:
        """Orders received between two clock times today ("HH:MM"), with channel, items and status."""
        po = per_order(led.query(date, start_ts=f"{date}T{start}:00", end_ts=f"{date}T{end}:59"))
        out = []
        for oid, t in list(po.items())[:40]:
            r = t.get("order.received")
            out.append({"order_id": oid, "channel": r.payload.get("channel") if r else None,
                        "items": (r.payload.get("items") if r else None),
                        "status": "cancelled" if "order.cancelled" in t else ("handed_off" if "order.handed_off" in t else "open")})
        return out

    def get_rules(topic: str) -> list:
        """Up to 3 ops rules from the knowledge base about a topic (item, station or event)."""
        return _kb().retrieve({"item": topic}, ["ops_rule"], 3, 300, as_of=date)

    agent = llm.build_agent(model, "exceptions",
                            "You triage operational exceptions for a ramen shop during service. For each trigger id in "
                            "{trigger_ids?}, call get_trigger (and get_orders / get_rules if useful), then decide: "
                            "'alert' (text the manager now), 'present' (hand to the intake controller, e.g. pause an "
                            "item or quote longer) or 'note' (for the close review). Reply ONLY with JSON: "
                            '[{"id": ..., "decision": ..., "note": one or two sentences}].',
                            [get_trigger, get_orders, get_rules], "exceptions")
    out = llm.run(agent, {"date": date, "trigger_ids": list(by_id)}, f"Triage {len(by_id)} new exceptions for {date}.")
    parsed = llm.parse_json(out["state"].get("exceptions") or out["finals"].get("exceptions"))
    facts = llm.tool_facts(out["state"]) + [by_id]
    res = {}
    for x in parsed if isinstance(parsed, list) else []:
        if not isinstance(x, dict) or x.get("id") not in by_id or x.get("decision") not in DECISIONS:
            continue
        note = str(x.get("note") or "")[:400]
        if not note or not check_numbers(note, facts)["ok"]:
            continue
        res[x["id"]] = {"decision": x["decision"], "note": note, "by": "exceptions-agent"}
    return res


# ------------------------------------------------------------------ scanning
def raised(date: str, led: Ledger | None = None) -> list[dict]:
    led = led or ledger()
    res = {e.payload.get("id"): e for e in led.query(date, ["exception.resolved"])}
    out = []
    for e in led.query(date, ["exception.raised"]):
        p = e.payload
        out.append({"id": p.get("id"), "ts": e.ts, "kind": p.get("kind"), "severity": p.get("severity"), "title": p.get("title"),
                    "decision": p.get("decision"), "note": p.get("note"), "evidence": p.get("evidence"), "by": p.get("by"),
                    "alert": p.get("alert"), "resolved": p.get("id") in res,
                    "resolved_at": res[p["id"]].ts if p.get("id") in res else None})
    return out


def resolve(date: str, exc_id: str, by: str = "manager", led: Ledger | None = None, ts: str | None = None) -> bool:
    led = led or ledger()
    if exc_id not in {x["id"] for x in raised(date, led)}:
        return False
    led.append("exception.resolved", date, ts or datetime.now().isoformat(timespec="seconds"), {"id": exc_id, "by": by},
               source="review", key=f"review:exception.resolved:{exc_id}")
    return True


def scan(date: str, now: datetime | None = None, led: Ledger | None = None, db=DB, notifier=None, model=None,
         send: bool = True) -> list[dict]:
    """Run every trigger as of `now`; decide and record each NEW exception (exception.raised, keyed by trigger id so a
    trigger is raised once). Alerts from one scan go out as one bundled Sentinel text (quiet hours, dedupe).
    send=False (history): record decisions, text nobody."""
    led = led or ledger()
    if now is None:
        from ..ledger.build import horizon
        h = horizon(date, db)
        now = h or (datetime.fromisoformat(date) + timedelta(hours=27, minutes=59))
    have = {x["id"] for x in raised(date, led)}
    new = [c for c in candidates(date, now, led, db) if c["id"] not in have]
    if not new:
        return []
    decided: dict[str, dict] = {}
    if model is None:
        from .llm import configured_model
        model = configured_model()
    if model is not None and model is not False:
        try:
            decided = decide_llm(new, model, date, led)
        except Exception:  # noqa: BLE001 - the rules always have an answer
            decided = {}
    from ..kb import kb as _kb
    out = []
    for c in new:
        d = decided.get(c["id"])
        if d is None:
            topic = (next(iter(c["evidence"].get("top_items") or {}), None) or c["evidence"].get("station") or "")
            rules = _kb().retrieve({"item": topic}, ["ops_rule"], 3, 300, as_of=date) if topic else []
            d = decide_offline(c, rules)
        rec = {"id": c["id"], "kind": c["kind"], "severity": c["severity"], "title": c["title"], "decision": d["decision"],
               "note": d["note"], "by": d["by"], "evidence": c["evidence"]}
        out.append({**rec, "ts": c["ts"]})
    alerts = [x for x in out if x["decision"] == "alert"]
    alert_rec = None
    if alerts and send:
        alert_rec = _send(date, alerts, now, notifier)
    for x in out:
        if x["decision"] == "alert":
            x["alert"] = {"status": alert_rec.get("status") if alert_rec else "not sent (history)",
                          "key": alert_rec.get("key") if alert_rec else None}
        led.append("exception.raised", date, x["ts"], {k: v for k, v in x.items() if k != "ts"}, source="review",
                   key=f"review:exception:{x['id']}")
    return out


def _send(date: str, alerts: list[dict], now: datetime, notifier=None) -> dict:
    from ..tools import sentinel
    from ..ledger import out_dir
    notifier = notifier or sentinel.Notifier(outbox=out_dir() / "outbox.jsonl")
    texts = [a["note"].split(". ")[0] for a in alerts]
    body = sentinel.bundle_sms(texts, f"{pd.Timestamp(date):%a} {now:%H:%M}").replace("Gondola close", "Gondola")
    key = "exc-" + hashlib.sha1("|".join(sorted(a["id"] for a in alerts)).encode()).hexdigest()[:16]
    return notifier.send_sms(key, body, now)


# ------------------------------------------------------------------ background loop (started by the API)
_LOOP: dict = {"thread": None, "stop": None, "last": None, "runs": 0, "errors": 0}


def loop_once(db=DB) -> dict:
    """While the store is open: scan today's ledger and write the hourly shift logs."""
    from .. import now as clock
    from ..ledger.build import build_day
    from . import digests as dg
    info = clock.info(db)
    if info["phase"] != "open":
        return {"phase": info["phase"], "new": 0}
    today = info["today"]
    build_day(today, db)  # keep the order-level ledger current (idempotent)
    new = scan(today, clock.wall(), db=db)
    dg.write_shift_logs(today, clock.wall().hour)
    _LOOP["last"] = datetime.now().isoformat(timespec="seconds")
    return {"phase": "open", "new": len(new)}


def start_loop(interval_s: float = 60.0, db=DB) -> bool:
    """Start the every-minute loop once per process (GONDOLA_REVIEW_LOOP=0 disables it)."""
    import os
    if os.getenv("GONDOLA_REVIEW_LOOP", "1") == "0":
        return False
    if _LOOP["thread"] is not None and _LOOP["thread"].is_alive():
        return False
    stop = threading.Event()

    def run():
        while not stop.is_set():
            try:
                loop_once(db)
                _LOOP["runs"] += 1
            except Exception:  # noqa: BLE001 - keep watching
                _LOOP["errors"] += 1
            stop.wait(interval_s)
    t = threading.Thread(target=run, name="gondola-exceptions", daemon=True)
    _LOOP.update(thread=t, stop=stop)
    t.start()
    return True


def loop_status() -> dict:
    t = _LOOP["thread"]
    return {"running": bool(t and t.is_alive()), "last": _LOOP["last"], "runs": _LOOP["runs"], "errors": _LOOP["errors"]}
