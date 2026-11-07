"""Close Coordinator: runs the close as a dependency graph, in parallel where possible, and fails soft.

    python -m gondola.pipeline --date 2026-11-05

Phases
  1 Reconcile (parallel): Books, Stock, Demand
  2 Understand and prepare: Analyst, then Plan
  3 Cross-check
  4 Communicate (parallel): Sentinel, Report
  5 Protect: Guard arms the approved safety net
Then a 5 a.m. pass re-checks money (see morning_pass).

This is the offline runner: the steps call the same tools the ADK agents use, and the wording comes from
templates. With an LLM attached, only the wording changes; numbers are checked by agents.guardrails.
"""
from __future__ import annotations

from gondola import NP, clock
import argparse
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import Store, ROOT
from .report.render import curve_svg, render_report
from .storage import Bucket
from .paths import rel
from .agents.guardrails import check_numbers
from .tools import analyst, books, demand, guard, plan, sentinel, stock

STORE_ID, STORE_NAME = "hanabi-sqh", "Hanabi Ramen, Squirrel Hill"
OUT = ROOT / "out"
CHANNEL_NAME = {"doordash": "DoorDash", "ubereats": "Uber Eats", "grubhub": "Grubhub", "in_store": "In-store"}
DISPUTE_WINDOW_DAYS = 14


class StepError(Exception):
    pass


# Optional progress callback (set for the duration of one run_close call). The API uses it to stream steps.
_EMIT = None


def _emit(name: str, payload: dict):
    cb = _EMIT
    if cb is not None:
        try:
            cb(name, payload)
        except Exception:  # a broken listener must never break the close
            pass


def _timed(name, fn, log, fail: set):
    t0 = time.perf_counter()
    _emit("step", {"step": name, "status": "running"})
    try:
        if name in fail:
            raise StepError(f"injected failure in {name}")
        res = fn()
        log.append({"step": name, "status": "done", "seconds": round(time.perf_counter() - t0, 2)})
        _emit("step", {"step": name, "status": "done", "seconds": round(time.perf_counter() - t0, 2)})
        return res
    except Exception as e:  # fail soft: record, continue
        log.append({"step": name, "status": "failed", "seconds": round(time.perf_counter() - t0, 2), "error": str(e),
                    "trace": traceback.format_exc(limit=2)})
        _emit("step", {"step": name, "status": "failed", "seconds": round(time.perf_counter() - t0, 2), "message": str(e)})
        return None


def _state_path():
    return OUT / "closes.json"


def _load_state() -> dict:
    p = _state_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save_state(s: dict):
    OUT.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps(s, indent=1, default=str), encoding="utf-8")


# ------------------------------------------------------------------ steps
def step_books(db, date: str, as_of: datetime, verified: set) -> dict:
    """verified: 'date|channel' pairs already checked by an EARLIER close (a re-run of this close redoes its own)."""
    st = Store(db)
    cash = books.cash_variance(st, date)
    money = books.day_money(st, date)
    avail = st.df("SELECT DISTINCT business_date, channel FROM payout_lines WHERE CAST(available_at AS TIMESTAMP) <= ? "
                  "AND business_date >= ?", [as_of, (pd.Timestamp(date) - pd.Timedelta(days=DISPUTE_WINDOW_DAYS)).date()])
    pairs = {(str(pd.Timestamp(r.business_date).date()), r.channel) for r in avail.itertuples()}
    pairs = {p for p in pairs if f"{p[0]}|{p[1]}" not in verified}
    by_date: dict = {}
    for d_, ch in pairs:
        by_date.setdefault(d_, []).append(ch)
    verifications = [books.match_payouts(st, d_, sorted(chs)) for d_, chs in sorted(by_date.items())]
    # which reports arrived since the previous close (only these may trigger a text; older ones go in the report)
    fresh = st.df("SELECT DISTINCT business_date, channel FROM payout_lines WHERE CAST(available_at AS TIMESTAMP) BETWEEN ? AND ?",
                  [as_of - timedelta(hours=24), as_of])
    fresh_keys = {(str(pd.Timestamp(r.business_date).date()), r.channel) for r in fresh.itertuples()}
    for v in verifications:
        for c in v["channels"]:
            c["fresh"] = (v["date"], c["channel"]) in fresh_keys
    # tonight's estimate for today (reports not in yet)
    est = books.match_payouts(st, date, [])  # no reports yet: expected only
    o = st.df("SELECT channel, COUNT(*) n, SUM(subtotal) s, SUM(CAST(promo AS INT)) p FROM orders WHERE business_date = ? "
              "AND status='completed' AND channel <> 'in_store' GROUP BY 1", [date])
    estimate = [{"channel": r.channel, "orders": int(r.n), "sales": round(float(r.s), 2),
                 "expected": round(float(r.s * (1 - books.CONTRACT[r.channel]) - r.p * books.MARKETING_PER_PROMO_ORDER), 2),
                 "reported": None, "difference": None} for r in o.itertuples()]
    return {"cash": cash, "money": money, "verified": verifications, "estimate_today": estimate,
            "verified_pairs": sorted(f"{d_}|{ch}" for d_, ch in pairs)}


def step_stock(db, date: str) -> dict:
    st = Store(db)
    led = stock.update_ledger(st, date)
    chashu = stock.chashu_today(st, date)
    return {"ledger": led, "chashu": chashu}


def step_demand(db, date: str, backtest_cache: Path) -> dict:
    st = Store(db)
    tomorrow = str((pd.Timestamp(date) + pd.Timedelta(days=1)).date())
    cache = pd.read_csv(backtest_cache) if backtest_cache.exists() else pd.DataFrame(columns=["date"])
    daily = st.daily_frame()
    want = daily[(daily.business_date <= pd.Timestamp(date)) & (daily.orders > 0)].business_date.tail(61)
    want = [str(x.date()) for x in want]
    have = set(cache.date.astype(str))
    new = [demand.backtest_forecast(st, d_, daily) for d_ in want if d_ not in have]
    new = [x for x in new if x is not None]
    if new:
        cache = pd.concat([cache, pd.DataFrame(new)], ignore_index=True).drop_duplicates("date", keep="last").sort_values("date")
        cache.to_csv(backtest_cache, index=False)  # never overwrite with a filtered frame
    bt = cache[cache.date.astype(str).isin(want)].sort_values("date")
    bt60 = bt[bt.date.astype(str) < date].tail(60)  # calibrate on days before tonight
    if len(bt60) < 20:  # early history: not enough backtests for a calibrated range
        fc = demand.naive_forecast(st, tomorrow)
    else:
        fc = demand.run_forecast(st, tomorrow, bt60)
    # score the forecast that was actually stored last night, if there is one
    stored = OUT / "forecasts" / f"{date}.json"
    arow = daily.loc[daily.business_date == pd.Timestamp(date), "orders"]
    actual = float(arow.iloc[0]) if len(arow) else None
    if actual is None:
        fc["today_check"] = {"predicted": None, "actual": None, "error_pct": None, "source": "closed"}
    elif stored.exists():
        p50 = json.loads(stored.read_text(encoding="utf-8"))["p50"]
        fc["today_check"] = {"predicted": p50, "actual": actual, "error_pct": round((p50 - actual) / actual, 4), "source": "stored"}
    else:
        row = bt[bt.date.astype(str) == date]
        fc["today_check"] = ({**row.iloc[0].to_dict(), "source": "re-run"} if len(row) else
                             {"predicted": None, "actual": actual, "error_pct": None, "source": "none"})
    (OUT / "forecasts").mkdir(parents=True, exist_ok=True)
    (OUT / "forecasts" / f"{tomorrow}.json").write_text(json.dumps({k: fc[k] for k in ("date", "p10", "p50", "p90")}), encoding="utf-8")
    fc["naive_mape_60d"] = round(float(bt60.naive_error_pct.abs().mean()), 4) if len(bt60) else None
    fc.setdefault("backtest_mape_60d", round(float(bt60.error_pct.abs().mean()), 4) if len(bt60) else None)
    return fc


def step_analyst(db, date: str) -> dict:
    st = Store(db)
    daily = st.daily_frame()
    return {"compare": analyst.compare_periods(st, date, daily=daily), "explain": analyst.explain_change(st, date),
            "similar": analyst.find_similar_days(st, date, 5, daily), "curve": analyst.rush_curve(st, date).n.tolist(),
            "items": analyst.item_mix(st, date).head(8).to_dict("records")}


def step_plan(db, date: str, fc: dict, stock_res: dict | None, portion_counts: dict | None = None) -> dict:
    st = Store(db)
    sims = [s["date"] for s in fc["similar_days"]]
    ppo = float(np.mean(plan.chashu_portions_per_order(st, sims)))
    if fc["p50"] <= 0:  # store closed tomorrow: nothing to prep
        return {"portions_per_order": round(ppo, 3), "newsvendor": {"chashu_portions": 0}, "old_par": None, "old_runout": None,
                "safety_net": {"pause_apps_at": None, "trigger": "closed tomorrow"}, "staff_gaps": [], "prep_schedule": [],
                "card": [], "portion_counts": portion_counts or {}, "closed_tomorrow": True}
    nv = plan.newsvendor_par(fc["p10"], fc["p50"], fc["p90"], ppo)
    # tonight's habit: avg of the last 4 same weekdays x 1.10
    hist = st.df("SELECT business_date, used FROM prep_log WHERE dayofweek(business_date) = ? AND business_date <= ? "
                 "ORDER BY 1 DESC LIMIT 4", [int((pd.Timestamp(fc['date']).dayofweek + 1) % 7), date])
    old_par = int(np.ceil(hist.used.mean() * 1.10 / 10) * 10) if len(hist) else None
    safety = plan.safety_net_rule(fc["curve"], nv["chashu_portions"], ppo)
    old_runout = plan.safety_net_rule(fc["curve"], old_par, ppo, buffer_orders=0) if old_par else None
    sched = {h: (2 if 11 <= h < 17 else 3) for h in range(11, 23)}
    gaps = plan.staff_gaps(fc["curve"], sched)
    rush_start = int(fc["rush"]["start"][:2]) * 60 + int(fc["rush"]["start"][3:])
    tasks = [{"name": "Braise chashu", "minutes": 150, "deadline": rush_start - 60},
             {"name": "Slice and portion chashu", "minutes": 40, "deadline": rush_start - 15, "needs": "Braise chashu"},
             {"name": "Marinate eggs", "minutes": 30, "deadline": rush_start - 120},
             {"name": "Fold gyoza", "minutes": 90, "deadline": rush_start - 30},
             {"name": "Karaage marinade", "minutes": 25, "deadline": rush_start - 90}]
    leftover = (portion_counts or {}).get("chashu", 0)
    card = [plan.close_card("Chashu", nv["chashu_portions"], leftover, fc["curve"], ppo, busy_ratio=fc["p90"] / fc["p50"] * 1.1)]
    try:  # Future: the other limited items (ajitama egg, gyoza, tonkotsu broth) after chashu; additive, fails soft
        from .future.items import extra_cards
        card += extra_cards(st, fc, portion_counts)
    except Exception:  # noqa: BLE001
        pass
    return {"portions_per_order": round(ppo, 3), "newsvendor": nv, "old_par": old_par, "old_runout": old_runout,
            "safety_net": safety, "staff_gaps": gaps, "prep_schedule": plan.prep_schedule(tasks, cooks=2), "card": card,
            "portion_counts": portion_counts or {}}


def cross_check(res: dict) -> list[str]:
    issues = []
    b, a, fc = res.get("books"), res.get("analyst"), res.get("demand")
    if b and a:
        v1, v2 = b["money"]["net_sales"], a["compare"]["net_sales"]["value"]
        if abs(v1 - v2) > 0.01:
            issues.append(f"net sales disagree: books {v1} vs analyst {v2}")
    if fc and not (fc["p10"] <= fc["p50"] <= fc["p90"]):
        issues.append("forecast range out of order")
    if fc and sum(c["orders"] for c in fc["curve"]) - fc["p50"] > 1:
        issues.append("intraday curve does not sum to the daily forecast")
    p = res.get("plan")
    if p and p["newsvendor"]["chashu_portions"] <= 0 and not p.get("closed_tomorrow"):
        issues.append("non-positive prep par")
    return issues


def findings_from(res: dict, date: str) -> list[dict]:
    out = []
    b = res.get("books")
    if b:
        c = b["cash"]
        if c.get("flag") and c["difference"] < 0:
            out.append({"kind": "cash_short", "impact_usd": -c["difference"], "expected": c["expected"], "counted": c["counted"],
                        "title": f"Cash drawer short ${-c['difference']:.2f}"})
        for v in b["verified"]:
            for ch in v["channels"]:
                diff = ch["difference"]
                if diff < -1:
                    fs = [f for f in v["findings"] if f["channel"] == ch["channel"] and f["impact_usd"] > 0]
                    nerr = sum(1 for f in fs if f["kind"].startswith("error_charge"))
                    nmiss = sum(1 for f in fs if f["kind"] == "missing_from_payout")
                    parts = [f"{nerr} disputable charge{'s' if nerr != 1 else ''}" if nerr else None,
                             f"{nmiss} missing order{'s' if nmiss != 1 else ''}" if nmiss else None,
                             "commission above contract" if any(f["kind"] == "commission_overcharge" for f in fs) else None]
                    nvalid = sum(1 for f in v["findings"] if f["channel"] == ch["channel"] and f["kind"] == "error_charge_likely_valid")
                    if nvalid:
                        parts.append(f"{nvalid} valid-looking charge{'s' if nvalid != 1 else ''}")
                    rec = round(sum(f["impact_usd"] for f in fs), 2)
                    n_disp = sum(1 for f in fs if f["impact_usd"] > 0)
                    out.append({"kind": "payout_short", "channel": ch["channel"], "channel_name": CHANNEL_NAME[ch["channel"]],
                                "fresh": ch.get("fresh", False), "recoverable_usd": rec, "for_date_iso": v["date"], "n_disputable": n_disp,
                                "for_date": pd.Timestamp(v["date"]).strftime(f"%a %b %{NP}d"), "impact_usd": round(-diff, 2),
                                "detail": ", ".join(p for p in parts if p) or "unexplained", "title": f"{CHANNEL_NAME[ch['channel']]} short ${-diff:,.2f} for {pd.Timestamp(v['date']).strftime(f'%a %b %{NP}d')}"})
    if b and b["cash"].get("status") == "drawer_not_closed":
        out.append({"kind": "drawer_not_closed", "title": "Cash drawer not counted yet", "impact_usd": None})
    so = res.get("sold_out")
    if so:
        out.append({"kind": "sold_out_tonight", **so, "impact_usd": None,
                    "title": f"Chashu sold out at {so['at']}; {so['app_cancels']} app orders were cancelled while it was still live"})
    s = res.get("stock")
    if s and s["ledger"].get("findings"):
        for f in s["ledger"]["findings"]:
            out.append({**f, "impact_usd": None})
    p, fc = res.get("plan"), res.get("demand")
    if p and fc and p.get("old_runout") and p["old_runout"].get("pause_apps_at"):
        t = p["old_runout"]["pause_apps_at"]
        if t <= fc["rush"]["end"]:
            out.append({"kind": "runout_before_rush", "time": t, "par": p["newsvendor"]["chashu_portions"],
                        "title": f"Chashu runs out around {t} at the usual prep"})
    a = res.get("analyst")
    if res.get("cancel_rate") is not None:
        out.append({"kind": "cancel_rate", "rate": res["cancel_rate"], "prev_rate": res.get("prev_cancel_rate", 0.0), "title": f"DoorDash 7-day cancellation rate {res['cancel_rate']:.1%}"})
    return out


def report_context(res: dict, date: str) -> dict:
    d = pd.Timestamp(date)
    a, b, fc, p = res.get("analyst"), res.get("books"), res.get("demand"), res.get("plan")
    cmp_ = a["compare"] if a else None
    pct = lambda x: f"{x:+.0%} vs a usual {d.day_name()}" if (x is not None and x == x) else "no baseline yet"
    kpis = []
    if b and cmp_:
        neg = lambda x: x is not None and x == x and x < 0
        kpis = [{"label": "Net sales", "value": f"${b['money']['net_sales']:,.0f}", "delta": pct(cmp_["net_sales"]["change_pct"]), "bad": neg(cmp_["net_sales"]["change_pct"])},
                {"label": "Orders", "value": f"{b['money']['orders']}", "delta": pct(cmp_["orders"]["change_pct"]), "bad": neg(cmp_["orders"]["change_pct"])},
                {"label": "Average ticket", "value": f"${b['money']['avg_ticket']:.2f}", "delta": pct(cmp_["avg_ticket"]["change_pct"]), "bad": False},
                {"label": "Labour", "value": f"{b['money']['labour_pct']:.1%}", "delta": "of net sales", "bad": b['money']['labour_pct'] > 0.30}]
    fnd = res.get("findings", [])
    attention = [sentinel.short_text(f) for f in fnd if f.get("urgency") == "urgent"]
    older = [f for f in fnd if f["kind"] == "payout_short" and f.get("urgency") != "urgent"]
    if older:
        rec = round(sum(f.get("recoverable_usd") or 0 for f in older), 2)
        res["older_recoverable_usd"] = rec  # a derived number is a fact only once a tool step records it
        attention.append(f"{len(older)} older payout reports checked: ${rec:,.2f} looks recoverable (checklist on page 2)")
    for f in fnd:
        if f["kind"] == "usage_variance":
            attention.append(f["title"])
    if p and p.get("staff_gaps"):
        g = p["staff_gaps"][0]
        attention.append(f"Tomorrow needs +{g['extra_cooks']} cook {g['start']}–{g['end']}")
    attention = attention[:6]
    if not attention:
        attention = ["Nothing urgent tonight."]
    steps_failed = [s["step"] for s in res["log"] if s["status"] == "failed"]
    if steps_failed:
        attention.append(f"Not included tonight: {', '.join(steps_failed)} (retrying at 5 am).")
    ctxd = a["explain"]["context"] if a else {"events": [], "rain": False}
    context_line = ", ".join([w for w in ["Rain" if ctxd.get("rain") else None] + ctxd.get("events", []) if w]) or "No weather or events of note"
    payouts = []
    if b:
        fresh_v = [v for v in b["verified"] if any(c.get("fresh") for c in v["channels"])] or b["verified"][-1:]
        for v in fresh_v:
            for c in v["channels"]:
                if not c.get("fresh") and len(fresh_v) > 1:
                    continue
                payouts.append({"channel": f"{CHANNEL_NAME[c['channel']]} · {pd.Timestamp(v['date']):%a %b %{NP}d}", "status": "Verified",
                                "sales": c["sales"], "expected": c["expected"], "reported_s": f"${c['reported']:,.2f}",
                                "difference": c["difference"], "diff_s": f"{c['difference']:+,.2f}"})
        for c in b["estimate_today"]:
            payouts.append({"channel": f"{CHANNEL_NAME[c['channel']]} · tonight", "status": "Estimated", "sales": c["sales"],
                            "expected": c["expected"], "reported_s": "arrives later", "difference": None, "diff_s": ""})
    disputes = []
    if b:
        for v in b["verified"]:
            for f in v["findings"]:
                if f["kind"] == "error_charge_disputable":
                    left = DISPUTE_WINDOW_DAYS - (d - pd.Timestamp(v["date"])).days
                    disputes.append({"order": f["evidence"][0], "amount": f["impact_usd"], "reason": f["detail"]["reason"],
                                     "days_left": left, "channel": CHANNEL_NAME[f["channel"]]})
        disputes = sorted([x for x in disputes if x["days_left"] > 0], key=lambda x: (-x["amount"]))[:5]
    usual_curve = []
    if a:
        base_dates = a["compare"]["baseline_dates"]
        st = Store(res["db"])
        q = """SELECT business_date, time_bucket(INTERVAL 15 MINUTE, created_at) AS bin, COUNT(*) n FROM orders
               WHERE business_date IN (SELECT unnest(?::DATE[])) GROUP BY 1,2"""
        x = st.df(q, [base_dates]); x["slot"] = x.bin.dt.hour * 4 + x.bin.dt.minute // 15
        usual_curve = x.groupby("slot").n.mean().reindex(range(44, 92), fill_value=0).tolist()
        tc = analyst.rush_curve(st, date); tc["slot"] = tc.bin.dt.hour * 4 + tc.bin.dt.minute // 15
        today_curve = tc.set_index("slot").n.reindex(range(44, 92), fill_value=0).tolist()
    headline = "Close report"
    if res.get("closed_day"):
        headline = f"Closed today, {d:%A}"
    elif cmp_ and cmp_["net_sales"]["change_pct"] is not None:
        ch = cmp_["net_sales"]["change_pct"]
        headline = ("A strong night" if ch > 0.05 else "A quiet night" if ch < -0.05 else "A steady night") + f", {d:%A}"
    summary = ""
    if b and cmp_:
        summary = (f"{b['money']['orders']} orders and ${b['money']['net_sales']:,.0f} in net sales ({pct(cmp_['net_sales']['change_pct'])}). "
                   f"{context_line}. " + (f"Tomorrow looks like {fc['p50']:.0f} orders, with the rush {clock(fc['rush']['start'])}–{clock(fc['rush']['end'])}." if fc else ""))
    tom = {}
    if fc and p:
        tom = {"p50": f"{fc['p50']:.0f}", "p10": f"{fc['p10']:.0f}", "p90": f"{fc['p90']:.0f}", "rush": f"{clock(fc['rush']['start'])}–{clock(fc['rush']['end'])}",
               "similar": ", ".join(pd.Timestamp(s["date"]).strftime(f"%b %{NP}d") for s in fc["similar_days"][:3]),
               "par": p["newsvendor"]["chashu_portions"], "old_par": p["old_par"],
               "safety": (f"pause chashu on the apps at {p['safety_net']['pause_apps_at']} or {p['safety_net']['trigger']}, keep it for dine-in"
                          if p["safety_net"]["pause_apps_at"] else f"pause chashu on the apps {p['safety_net']['trigger']}"),
               "card": p.get("card", []),
               "staff": ("; ".join(f"+{g['extra_cooks']} cook {g['start']}–{g['end']}" for g in p["staff_gaps"][:2]) or "schedule covers the forecast")}
    check = {}
    if fc and fc.get("today_check", {}).get("predicted") is not None and fc.get("backtest_mape_60d") is not None:
        tc_ = fc["today_check"]
        check = {"predicted": f"{tc_['predicted']:.0f}", "actual": f"{tc_['actual']:.0f}", "err": f"{tc_['error_pct']:+.1%}",
                 "mape": f"{fc['backtest_mape_60d']:.1%}", "naive": f"{fc['naive_mape_60d']:.1%}",
                 "source": "last night's stored forecast" if tc_.get("source") == "stored" else "a re-run with only last night's data"}
    lab = b["money"] if b and b["money"].get("labour_pct") is not None else None
    return {"store_name": STORE_NAME, "date": date, "date_long": d.strftime(f"%A, %B %{NP}d, %Y"), "dow_name": d.day_name(),
            "headline": headline, "summary": summary, "kpis": kpis, "attention": attention,
            "curve_svg": curve_svg(today_curve, usual_curve) if a else "", "channels": a["explain"]["channel"] if a else [],
            "context_line": context_line, "payouts": payouts,
            "cash": b["cash"] if b and b["cash"].get("difference") is not None else None,
            "labour_line": f"{lab['labour_hours']:.0f} hours, ${lab['labour_cost']:,.0f} ({lab['labour_pct']:.1%} of net sales)" if lab else "n/a",
            "disputes": disputes, "tomorrow": tom, "check": check, "generated": pd.Timestamp(res["as_of"]).strftime(f"%b %{NP}d %{NP}I:%M %p"), "rebuilt": None,
            "closed_day": res.get("closed_day", False)}


def night_facts(res: dict) -> dict:
    """One line per night for the Reports list: what the night was and what Gondola did about it."""
    b, a = res.get("books") or {}, res.get("analyst") or {}
    money = b.get("money") or {}
    fnd = res.get("findings") or []

    def sent(x):
        st_ = x.get("original_status") if x.get("status") == "duplicate_suppressed" else x.get("status")
        return x.get("channel", "sms") == "sms" and st_ in ("sent", "dry_run")
    return {"net_sales": money.get("net_sales"), "orders": money.get("orders"),
            "vs_usual_pct": ((a.get("compare") or {}).get("net_sales") or {}).get("change_pct"),
            "urgent": sum(1 for f in fnd if f.get("urgency") == "urgent"),
            "texted": any(sent(x) for x in res.get("alerts") or []),
            "recoverable_usd": round(sum(f.get("recoverable_usd") or 0 for f in fnd if f.get("kind") == "payout_short"), 2),
            "closed_day": bool(res.get("closed_day"))}


# ------------------------------------------------------------------ coordinator
def run_close(date: str, db: Path | str = ROOT / "data" / "gondola.duckdb", as_of: datetime | None = None,
              fail: set | None = None, force: bool = False, notifier: sentinel.Notifier | None = None,
              bucket: Bucket | None = None, render: bool = True, approve_plan: bool = True,
              executor: guard.Executor | None = None, portion_counts: dict | None = None, on_event=None,
              agent_model=None) -> dict:
    """portion_counts: what the manager confirmed is left of each limited item at close, e.g. {"chashu": 18}.
    on_event(name, payload): optional progress callback (steps, findings, agent events).
    agent_model: run the ADK agent graph for wording with this model (name or BaseLlm). None -> agent mode only if
    GONDOLA_AGENTS=adk and a model key are set (agents.adk_graph.configured_model); False -> never."""
    global _EMIT
    _EMIT = on_event
    try:
        return _run_close(date, db, as_of, fail, force, notifier, bucket, render, approve_plan, executor, portion_counts,
                          agent_model)
    finally:
        _EMIT = None


def _agent_wording(res: dict, date: str, agent_model) -> dict | None:
    """Agent mode: the ADK Close Coordinator graph writes the explanations on top of the pipeline's numbers.
    Fails soft: any error leaves the template wording in place."""
    if agent_model is False or res.get("closed_day"):
        return None
    try:
        from .agents import adk_graph
        model = agent_model if agent_model is not None else adk_graph.configured_model()
        if model is None:
            return None
        t0 = time.perf_counter()
        _emit("agent", {"agent": "close_coordinator", "status": "running"})
        out = adk_graph.run_close_graph(res, date, model=model, db=res["db"], on_event=_emit)
        out["seconds"] = round(time.perf_counter() - t0, 2)
        _emit("agent", {"agent": "close_coordinator", "status": "done", "seconds": out["seconds"]})
        return out
    except Exception as e:  # noqa: BLE001
        _emit("agent", {"agent": "close_coordinator", "status": "failed", "message": str(e)[:200]})
        return {"mode": "adk", "error": str(e)[:500], "outputs": {}}


def _run_close(date, db, as_of, fail, force, notifier, bucket, render, approve_plan, executor, portion_counts,
               agent_model=None) -> dict:
    fail = fail or set()
    state = _load_state()
    if date in state and state[date].get("status") in ("done", "partial", "closed") and not force:
        return {**state[date], "idempotent_hit": True}
    t0 = time.perf_counter()
    as_of = as_of or (pd.Timestamp(date) + pd.Timedelta(hours=23, minutes=10)).to_pydatetime()
    vb = state.get("_verified_by", {})
    verified = {pair for pair, by in vb.items() if by < date}  # a re-run redoes its own verifications
    log: list = []
    res: dict = {"date": date, "db": str(db), "log": log, "as_of": as_of.isoformat()}
    OUT.mkdir(parents=True, exist_ok=True)
    bt_cache = OUT / "backtest_cache.csv"

    n_today = Store(db).df("SELECT COUNT(*) n FROM orders WHERE business_date = ?", [date]).n[0]
    res["closed_day"] = bool(n_today == 0)
    if res["closed_day"]:
        fail = fail | {"books", "stock", "analyst"}  # nothing to reconcile; still plan tomorrow
    with ThreadPoolExecutor(max_workers=3) as pool:  # phase 1: reconcile
        fb = pool.submit(_timed, "books", lambda: step_books(db, date, as_of, verified), log, fail)
        fs = pool.submit(_timed, "stock", lambda: step_stock(db, date), log, fail)
        fd = pool.submit(_timed, "demand", lambda: step_demand(db, date, bt_cache), log, fail)
        res["books"], res["stock"], res["demand"] = fb.result(), fs.result(), fd.result()
    res["analyst"] = _timed("analyst", lambda: step_analyst(db, date), log, fail)
    res["plan"] = _timed("plan", lambda: step_plan(db, date, res["demand"], res["stock"], portion_counts), log, fail) if res["demand"] else None
    if res["plan"] is None and not any(s["step"] == "plan" for s in log):
        log.append({"step": "plan", "status": "skipped", "seconds": 0, "error": "needs demand"})
    st = Store(db)
    w = st.df("""SELECT SUM(CASE WHEN status='cancelled' AND cancel_reason='item_unavailable' THEN 1 ELSE 0 END) c, COUNT(*) n
                 FROM orders WHERE channel='doordash' AND business_date BETWEEN ? AND ?""",
              [(pd.Timestamp(date) - pd.Timedelta(days=6)).date(), date])
    res["cancel_rate"] = float(w.c[0] / w.n[0]) if w.n[0] else None
    w2 = st.df("""SELECT SUM(CASE WHEN status='cancelled' AND cancel_reason='item_unavailable' THEN 1 ELSE 0 END) c, COUNT(*) n
                 FROM orders WHERE channel='doordash' AND business_date BETWEEN ? AND ?""",
               [(pd.Timestamp(date) - pd.Timedelta(days=7)).date(), (pd.Timestamp(date) - pd.Timedelta(days=1)).date()])
    res["prev_cancel_rate"] = float(w2.c[0] / w2.n[0]) if w2.n[0] else 0.0
    so = stock.sold_out_summary(st, date)
    if so:
        res["sold_out"] = so
    res["cross_check"] = cross_check(res)
    res["findings"] = findings_from(res, date)
    for f in res["findings"]:
        _emit("finding", {"kind": f.get("kind"), "title": f.get("title") or f.get("kind"),
                          "urgency": sentinel.score_urgency(f)})

    res["agents"] = _agent_wording(res, date, agent_model)  # None in offline mode

    notifier = notifier or sentinel.Notifier(outbox=OUT / "outbox.jsonl")
    alerts = []
    def do_sentinel():
        urgent = []
        for f in res["findings"]:
            tier = sentinel.score_urgency(f)
            f["urgency"] = tier
            if tier == sentinel.URGENT:
                urgent.append(f)
        if urgent:
            body = sentinel.bundle_sms([sentinel.short_text(f) for f in urgent], pd.Timestamp(date).strftime(f"%a %b %{NP}d"))
            g = check_numbers(body, [urgent])
            res["guardrail_sms"] = g
            if not g["ok"]:  # never send a number we can't trace to a tool result
                body = sentinel.bundle_sms([f.get("title", f["kind"]) for f in urgent], pd.Timestamp(date).strftime(f"%a %b %{NP}d"))
            alerts.append(notifier.send_sms(f"close-{STORE_ID}-{date}", body, as_of))
        failed = [s["step"] for s in log if s["status"] == "failed" and not res["closed_day"]]
        if failed:
            f = {"kind": "close_failed", "detail": ", ".join(failed) + " failed"}
            alerts.append(notifier.send_sms(sentinel.dedupe_key(STORE_ID, date, f), sentinel.sms_text(f), as_of, failure=True))
        return alerts
    _timed("sentinel", do_sentinel, log, fail)
    res["alerts"] = alerts

    def do_report():
        ctx = report_context(res, date)
        srcs = [res.get(k) for k in ("books", "analyst", "demand", "plan", "findings", "stock", "older_recoverable_usd")]
        ag = res.get("agents") or {}
        agent_summary = (ag.get("outputs") or {}).get("report")
        if agent_summary and not ag.get("guardrail_blocked", {}).get("report"):
            g = check_numbers(agent_summary, srcs)  # second check, against the pipeline's own numbers
            ag["report_check"] = g
            if g["ok"]:
                ctx["summary_template"], ctx["summary"], ctx["wording"] = ctx["summary"], agent_summary, "agents"
        res["guardrail_report"] = check_numbers(ctx["summary"] + " " + " ".join(ctx["attention"]), srcs)
        ctx["meta"] = night_facts(res)  # the Reports list reads these from findings.json (kept 365 days)
        r = render_report(ctx, OUT / "reports", f"{date}") if render else {"pdf": None}
        if render:
            (bucket or Bucket(OUT / "bucket")).put_daily(date, Path(r["pdf"]), OUT / "reports" / f"{date}.findings.json", created=as_of,
                                                         html=Path(r["html"]))
            card = (res.get("plan") or {}).get("card", [])
            card_txt = " ".join(f"Tomorrow's card: make {c['prep']} {c['item'].lower()}, pause on DoorDash ~{clock(c['pause_at']['doordash'] or c['pause_if_busy']['doordash']) or 'not needed'}"
                                f"{' if it is busy' if not c['pause_at']['doordash'] else ''}. "
                                "Approve in Gondola." for c in card)
            notifier.send_email(f"email-{date}", f"Daily Close Report · {pd.Timestamp(date):%a %b %{NP}d}", ctx["summary"] + " " + card_txt, r["pdf"], as_of,
                                stored_attachment=rel(r["pdf"], OUT))
        return {**r, "context": ctx}
    res["report"] = _timed("report", do_report, log, fail)

    if res["plan"] and approve_plan:
        ex = executor or guard.Executor()
        sn = res["plan"]["safety_net"]
        res["guard"] = _timed("guard", lambda: {"armed_rule": sn, "approved": True,
                                                 "note": "Rule armed; executor fires during service when the trigger is met."}, log, fail)
    # --- tri-workflow close hook (Ledger + Review team): the Review agent runs last, after every deterministic step.
    # It is additive: its failure is logged but never changes the close's status.
    if REVIEW_IN_CLOSE and not res["closed_day"]:
        res["review"] = _timed("review", lambda: _review_step(res, date, db, agent_model), log, fail)
    if res["closed_day"]:
        for s_ in log:
            if s_["status"] == "failed" and "injected" in s_.get("error", ""):
                s_["status"], s_["error"] = "skipped", "store closed"
    failed = [s_ for s_ in log if s_["status"] == "failed" and s_["step"] != "review"]
    res["status"] = ("closed" if res["closed_day"] else "done") if not failed and not res["cross_check"] else "partial"
    res["seconds"] = round(time.perf_counter() - t0, 2)
    res["run_id"] = f"{date}-{datetime.now():%Y%m%dT%H%M%S%f}"  # approvals are tied to one run of the close
    for pair in (res["books"] or {}).get("verified_pairs", []):
        if pair not in vb or vb[pair] >= date:
            vb[pair] = date
    state["_verified_by"] = vb
    state[date] = {"date": date, "status": res["status"], "seconds": res["seconds"], "log": log, "findings": res["findings"],
                   "cross_check": res["cross_check"], "pdf": rel((res["report"] or {}).get("pdf"), OUT)}
    _save_state(state)
    saved = {k: v for k, v in res.items() if k != "report"}
    saved["db"] = rel(db)  # never store absolute machine paths
    if saved.get("agents"):
        saved["agents"] = {k: v for k, v in saved["agents"].items() if k != "facts"}
    (OUT / f"close_{date}.json").write_text(json.dumps(saved, default=str, indent=1), encoding="utf-8")
    return res


REVIEW_IN_CLOSE = True  # tri-workflow: run gondola.review.agent at the end of the close (GONDOLA_REVIEW_IN_CLOSE=0 skips)


def _review_step(res: dict, date: str, db, agent_model) -> dict:
    """Ledger for the night, exception scan, Review agent, digests and knowledge base (gondola/review/agent.py).
    Stores live next to this close's out/ folder (gondola.ledger.out_dir follows OUT)."""
    import os
    if os.getenv("GONDOLA_REVIEW_IN_CLOSE", "1") == "0":
        return {"skipped": "GONDOLA_REVIEW_IN_CLOSE=0"}
    from .review.agent import run_review
    r = run_review(date, db=db, close_res=res, model=agent_model)
    return {"digest_id": r["digest_id"], "mode": r["mode"], "well": len(r["well"]), "wrong": len(r["wrong"]),
            "actions": [a["id"] for a in r["actions"]], "kb_changes": len(r["kb_changes"]),
            "context_tokens": r["context"]["tokens"]}


def morning_pass(date: str, db: Path | str = ROOT / "data" / "gondola.duckdb") -> dict:
    """5 a.m.: re-check money. Only messages again if a number changed."""
    st = Store(db)
    cash = books.cash_variance(st, date)
    state = _load_state()
    prev = [f for f in state.get(date, {}).get("findings", []) if f["kind"] == "cash_short"]
    changed = bool(prev) != bool(cash.get("flag") and cash["difference"] < 0)
    return {"date": date, "cash": cash, "changed": changed}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-11-05")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--chashu-left", type=float, default=None, help="portions left, confirmed by the manager at close")
    a = ap.parse_args()
    db = ROOT / "data" / "gondola.duckdb"
    last = Store(db).last_date()
    if pd.Timestamp(a.date) < last:  # closing a past night: use only the data that existed then
        from .connectors.ingest import ingest
        db = ingest(db_path=ROOT / "data" / f"asof_{a.date}.duckdb", upto=a.date)
    pc = {"chashu": a.chashu_left} if a.chashu_left is not None else None
    r = run_close(a.date, db=db, force=a.force, portion_counts=pc)
    print(json.dumps({"status": r["status"], "seconds": r["seconds"], "log": r["log"], "findings": r["findings"],
                      "alerts": r.get("alerts"), "cross_check": r["cross_check"]}, indent=1, default=str))
