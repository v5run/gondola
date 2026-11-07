"""Fast checks. The full scoring against ground truth is scripts/evaluate.py."""
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gondola.metrics import Store  # noqa: E402
from gondola.tools import books, plan, sentinel, stock, analyst  # noqa: E402
from gondola.agents.ask import ask  # noqa: E402
from gondola.agents.guardrails import check_numbers  # noqa: E402
from gondola.storage import Bucket  # noqa: E402

D = "2026-11-05"


@pytest.fixture(scope="session")
def st():
    return Store()


def test_data_integrity(st):
    o = st.df("SELECT COUNT(*) n, COUNT(DISTINCT order_id) u, MIN(subtotal) m FROM orders")
    assert o.n[0] == o.u[0] and o.m[0] > 0
    orphan = st.df("SELECT COUNT(*) n FROM payout_lines WHERE order_id NOT IN (SELECT order_id FROM orders)").n[0]
    assert orphan == 0
    assert st.df("SELECT COUNT(DISTINCT business_date) n FROM orders").n[0] >= 360


def test_metrics_agree_with_raw(st):
    raw = pd.read_csv(ROOT / "data/raw/pos_orders.csv")
    v = raw[(raw.business_date == D) & (raw.status == "completed")].subtotal.sum()
    assert abs(st.metric_total("net_sales", D) - v) < 0.01


def test_books_demo_day(st):
    r = books.match_payouts(st, "2026-11-04")
    dd = [c for c in r["channels"] if c["channel"] == "doordash"][0]
    assert -87 < dd["difference"] < -86
    assert sum(1 for f in r["findings"] if f["kind"] == "error_charge_disputable" and f["channel"] == "doordash") == 3
    c = books.cash_variance(st, D)
    assert c["difference"] == -23.50 and c["flag"]


def test_dispute_is_draft_only(st):
    r = books.match_payouts(st, "2026-11-04")
    f = [x for x in r["findings"] if x["kind"] == "error_charge_disputable"][0]
    txt = books.draft_dispute(f)
    assert f["evidence"][0] in txt and "submitted" not in txt.lower()


def test_similar_days_use_only_past(st):
    sims = analyst.find_similar_days(st, D, 5)
    assert all(pd.Timestamp(s["date"]) < pd.Timestamp(D) for s in sims)


def test_newsvendor_monotone():
    a = plan.newsvendor_par(400, 500, 600, 1.0)["chashu_portions"]
    b = plan.newsvendor_par(500, 600, 700, 1.0)["chashu_portions"]
    assert b > a > 500


def test_prep_schedule_respects_dependency():
    s = plan.prep_schedule([{"name": "A", "minutes": 60, "deadline": 900}, {"name": "B", "minutes": 30, "deadline": 1000, "needs": "A"}])
    t = {r["name"]: r for r in s}
    hm = lambda x: int(x.split(":")[0]) * 60 + int(x.split(":")[1])
    assert hm(t["B"]["start"]) >= hm(t["A"]["end"])


def test_sentinel_rules():
    assert sentinel.score_urgency({"kind": "cash_short", "impact_usd": 23.5}) == "urgent"
    assert sentinel.score_urgency({"kind": "cash_short", "impact_usd": 8}) == "important"
    assert sentinel.score_urgency({"kind": "payout_short", "impact_usd": 80, "fresh": False, "recoverable_usd": 80}) == "important"
    assert sentinel.in_quiet_hours(datetime(2026, 11, 6, 2, 0))


def test_sms_length_and_stop(tmp_path):
    n = sentinel.Notifier(tmp_path / "o.jsonl")
    body = sentinel.bundle_sms(["x" * 120] * 5, "Thu Nov 5")
    r = n.send_sms("k", body, datetime(2026, 11, 5, 23, 10))
    assert len(r["body"]) <= 345 and r["body"].endswith("Reply STOP to opt out.")
    assert n.send_sms("k", body, datetime(2026, 11, 5, 23, 11))["status"] == "duplicate_suppressed"


def test_guardrail_blocks_invented_numbers():
    assert check_numbers("Net sales $15,270.", [{"v": 15269.7}])["ok"]
    assert not check_numbers("Net sales $18,000.", [{"v": 15269.7}])["ok"]


@pytest.mark.parametrize("q", ["What were net sales yesterday?", "DoorDash orders in the last 7 days",
                               "Avoidable cancellations in the last 30 days", "Why was last Thursday slow?"])
def test_ask_answers_with_tool_calls(st, q):
    a = ask(st, q, D)
    assert a.calls and a.text


def test_bucket_lifecycle(tmp_path):
    b = Bucket(tmp_path)
    pdf = tmp_path / "r.pdf"; pdf.write_bytes(b"%PDF-1.4 test")
    fj = tmp_path / "r.json"; fj.write_text(json.dumps({"x": 1}))
    b.put_daily("2026-09-01", pdf, fj, created=datetime(2026, 9, 1, 23))
    b.put_daily("2026-11-01", pdf, fj, created=datetime(2026, 11, 1, 23))
    r = b.apply_lifecycle(datetime(2026, 11, 5, 23))
    assert r["expired"] == 1
    assert b.get("2026-11-01")["status"] == "stored"
    rebuilt = b.get("2026-09-01", rebuild=lambda ctx, d: pdf, now=datetime(2026, 11, 5))
    assert rebuilt["status"] == "rebuilt"


def test_ledger_runs(st):
    r = stock.update_ledger(st, D)
    assert r["rows"] and all("ledger" in x for x in r["rows"])


# ---- regressions from the independent QA pass -------------------------------------------------
def test_unarrived_reports_are_not_verified(st):
    from datetime import datetime
    from gondola.pipeline import step_books
    r = step_books(st.db_path, D, datetime(2026, 11, 5, 23, 10), set())
    pairs = set(r["verified_pairs"])
    assert "2026-11-04|doordash" in pairs          # DoorDash arrives D+1 evening
    assert "2026-11-04|ubereats" not in pairs      # Uber Eats takes up to 72 h


@pytest.mark.parametrize("q,expect", [("how many orders tomorrow", "Tomorrow"), ("asdfgh", "What would you like"),
                                      ("sales feb 30", "doesn't have a day"), ("sales on 2025-11-01", "only have data"),
                                      ("uber vs doordash last month", "DoorDash"), ("why was christmas slow", "closed"),
                                      ("how many tonkotsu did we sell yesterday", "Tonkotsu")])
def test_ask_clarifies_instead_of_guessing(st, q, expect):
    assert expect in ask(st, q, D).text


def test_closed_day_and_rerun(tmp_path):
    from gondola import pipeline
    from gondola.tools.sentinel import Notifier
    old = pipeline.OUT
    pipeline.OUT = tmp_path
    try:
        r = pipeline.run_close("2025-12-25", render=False, notifier=Notifier(tmp_path / "o.jsonl"))
        assert r["status"] == "closed"
        n = Notifier(tmp_path / "o2.jsonl")
        a = pipeline.run_close(D, render=False, notifier=n)
        b = pipeline.run_close(D, render=False, notifier=n, force=True)
        assert len(a["findings"]) == len(b["findings"])
        assert len((tmp_path / "o2.jsonl").read_text().splitlines()) == 1  # one text per close, however many taps
    finally:
        pipeline.OUT = old


def test_guardrail_rejects_ids_dates_and_near_misses():
    tools = [{"net_sales": 15269.70, "order_id": "o0172068", "date": "2026-11-05", "orders": 470}]
    assert check_numbers("Net sales $15,269.70 on 470 orders.", tools)["ok"]
    for bad in ["Net sales $15,340.", "Recoverable $172,068.", "Uber owes us $2,026.", "We did 512 orders."]:
        assert not check_numbers(bad, tools)["ok"], bad


# ---- V2: close card, per-app pause times, recount ---------------------------------------------
def test_close_card_uses_confirmed_leftover():
    curve = [{"bin": 72 + i, "time": f"{18 + i // 4}:{i % 4 * 15:02d}", "orders": 40.0} for i in range(16)]
    c = plan.close_card("Chashu", 400, 120, curve, 0.8)
    assert c["prep"] == 280 and c["on_hand"] == 120
    assert c["pause_at"]["grubhub"] <= c["pause_at"]["doordash"]  # slower app pauses earlier


def test_recount_makes_guard_robust(st):
    from gondola.tools import guard
    days = [str(pd.Timestamp(d).date()) for d in st.df("SELECT business_date FROM prep_log WHERE sold_out ORDER BY 1").business_date][-15:]
    no = sum(guard.guarded_day(st, d, count_error=0.08, delay_min=5, recount=False, seed=i)["cancels"] for i, d in enumerate(days))
    yes = sum(guard.guarded_day(st, d, count_error=0.08, delay_min=5, recount=True, seed=i)["cancels"] for i, d in enumerate(days))
    assert yes < no and yes <= 15


# ---- V2 QA regressions -----------------------------------------------------------------------
def test_close_card_rejects_bad_counts():
    curve = [{"bin": 72 + i, "time": f"{18 + i // 4}:{i % 4 * 15:02d}", "orders": 40.0} for i in range(16)]
    assert plan.close_card("Chashu", 400, 1200, curve, 0.8)["warnings"]
    assert plan.close_card("Chashu", 400, float("nan"), curve, 0.8)["prep"] == 400
    assert plan.close_card("Chashu", 400, -50, curve, 0.8)["warnings"]


def test_recount_trigger_uses_only_believed_count():
    import inspect
    from gondola.tools import guard
    src = inspect.getsource(guard.guarded_day)
    trig = [l for l in src.splitlines() if "if recount and not counted" in l][0]
    assert "true_left" not in trig


def test_closed_tomorrow_preps_nothing(tmp_path):
    from gondola import pipeline
    from gondola.tools.sentinel import Notifier
    old = pipeline.OUT; pipeline.OUT = tmp_path
    try:
        r = pipeline.run_close("2025-12-24", render=False, notifier=Notifier(tmp_path / "o.jsonl"))
        assert r["demand"]["p50"] == 0 and r["plan"]["card"] == []
    finally:
        pipeline.OUT = old
