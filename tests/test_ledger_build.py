"""Ledger build (orders/cash/payouts/forecasts -> events), idempotency, summaries vs direct pandas, prep-time learning,
and the Past API. Offline; every store lives in a temp out/ folder (gondola.pipeline.OUT)."""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gondola import pipeline  # noqa: E402
from gondola.ledger import Ledger, ledger  # noqa: E402
from gondola.ledger import build as B  # noqa: E402
from gondola.ledger.learning import learned_durations  # noqa: E402
from gondola.ledger.summary import summary  # noqa: E402
from gondola.metrics import Store  # noqa: E402
from gondola.tools import books  # noqa: E402

DATE = "2026-11-05"


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    for k in ("GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "GONDOLA_AGENTS", "GONDOLA_LEDGER_DB", "GONDOLA_KB_DB", "GONDOLA_DIGESTS_DB"):
        os.environ.pop(k, None)
    o = tmp_path_factory.mktemp("out_ledger")
    (o / "forecasts").mkdir()
    (o / "forecasts" / f"{DATE}.json").write_text(json.dumps({"date": DATE, "p10": 474.5, "p50": 527.4, "p90": 606.7}))
    old = pipeline.OUT
    pipeline.OUT = o
    yield o
    pipeline.OUT = old


@pytest.fixture(scope="module")
def built(out):
    led = ledger()
    assert led.path == out / "ledger.sqlite"  # follows pipeline.OUT
    first = B.build_day(DATE, B.DB, led)
    second = B.build_day(DATE, B.DB, led)
    return led, first, second


@pytest.fixture(scope="module")
def orders():
    st = Store(B.DB)
    df = st.df("SELECT * FROM orders WHERE business_date = ?", [DATE])
    st.con.close()
    return df


def test_build_is_idempotent(built):
    led, first, second = built
    assert first["new"] > 0 and second["new"] == 0
    assert led.count(DATE) == first["new"]


def test_build_matches_orders_table(built, orders):
    led, first, _ = built
    bt = first["by_type"]
    assert bt["order.received"] == len(orders) == bt["order.accepted"]
    assert bt["order.handed_off"] == int((orders.status == "completed").sum())
    assert bt["order.cancelled"] == int((orders.status == "cancelled").sum())
    assert bt["cash.counted"] == 1 and bt["forecast.issued"] == 1
    c = led.query(DATE, ["order.cancelled"])
    want = orders[orders.status == "cancelled"].cancel_reason.value_counts().to_dict()
    got = pd.Series([e.payload["reason"] for e in c]).value_counts().to_dict()
    assert got == want
    fc = led.query(DATE, ["forecast.issued"])[0]
    assert fc.payload["total"]["p50"] == 527.4 and fc.ts == "2026-11-04T23:10:00"


def test_payout_events_agree_with_books(built):
    led, _, _ = built
    reps = led.query(DATE, ["payout.report_arrived"])
    assert reps, "reports land on the demo night"
    st = Store(B.DB)
    for e in reps:
        m = books.match_payouts(st, e.payload["for_date"], [e.payload["channel"]])
        assert e.payload["difference"] == m["channels"][0]["difference"]
        assert e.date == DATE and e.ts.startswith(DATE)
    st.con.close()
    dd = [e for e in reps if e.payload["channel"] == "doordash"][0]
    assert dd.payload["for_date"] == "2026-11-04" and dd.payload["recoverable_usd"] == 86.4 and dd.payload["n_disputable"] == 3


def test_partial_day_is_cut(out, orders):
    led = Ledger(out / "partial.sqlite")
    r = B.build_day(DATE, B.DB, led, until=datetime(2026, 11, 5, 18, 0))
    assert r["by_type"]["order.received"] == int((orders.created_at < pd.Timestamp(f"{DATE} 18:00")).sum())
    assert "cash.counted" not in r["by_type"]  # the drawer is counted after close
    assert all(e.ts < f"{DATE}T18:00:00" for e in led.query(DATE) if e.type.startswith("order."))


def test_summary_vs_pandas(built, orders):
    led, _, _ = built
    s = summary(DATE, None, led)
    done = orders[orders.status == "completed"]
    assert s["processed"] == len(done)
    assert s["sales"] == pytest.approx(done.subtotal.sum(), abs=0.01)
    for ch, g in done.groupby("channel"):
        assert s["by_channel"][ch]["orders"] == len(g)
        assert s["by_channel"][ch]["sales"] == pytest.approx(g.subtotal.sum(), abs=0.01)
    assert s["cancels"] == int((orders.status == "cancelled").sum())
    assert s["timing_source"] == "none" and s["avg_wait_min"] is None and s["promises_met"] is None
    cut = summary(DATE, "18:00", led)
    early = orders[orders.created_at < pd.Timestamp(f"{DATE} 18:00")]
    assert cut["processed"] == int((early.status == "completed").sum()) and cut["cutoff"] == "18:00"


def test_summary_prefers_present_events(out, orders):
    led = Ledger(out / "present.sqlite")
    B.build_day(DATE, B.DB, led, until=None)
    ids = orders[orders.status == "completed"].order_id.tolist()[:3]
    rows = []
    for i, (oid, wait, hold, late) in enumerate(zip(ids, [8.0, 12.0, 20.0], [1.0, 0.0, 3.0], [-2.0, 0.0, 6.0])):
        rows.append({"type": "order.handed_off", "date": DATE, "ts": f"{DATE}T12:0{i}:00", "source": "present",
                     "key": f"order.handed_off:{oid}", "payload": {"order_id": oid, "channel": "doordash", "ready": "12:00",
                                                                     "handed": "12:01", "wait_min": wait, "hold_min": hold, "late_min": late}})
    rows.append({"type": "action.applied", "date": DATE, "ts": f"{DATE}T19:00:00", "source": "present", "key": "a1",
                 "payload": {"action": "quote", "channel": "doordash", "ladder_level": -1, "headroom_pct": -5, "reason": "t", "by": "controller"}})
    led.extend(rows)
    s = summary(DATE, None, led)
    assert s["processed"] == int((orders.status == "completed").sum())  # no double counting across writers
    assert s["promises_total"] == 3 and s["promises_met"] == 2 and s["late_orders"] == 1
    assert s["avg_wait_min"] == pytest.approx(13.3, abs=0.05) and s["worst_wait_min"] == 20.0
    assert s["avg_hold_min"] == pytest.approx(1.3, abs=0.05) and s["actions_count"] == 1 and s["timing_source"] == "present"


def test_learned_durations_ema(out):
    led = Ledger(out / "learn.sqlite")
    obs = [5.0, 7.0, 6.0]
    led.extend([{"type": "task.finished", "date": DATE, "ts": f"{DATE}T18:0{i}:00", "source": "present", "key": f"t{i}",
                 "payload": {"order_id": f"o{i}", "task_id": f"t{i}", "item": "Gyoza", "station": "fryer", "planned_min": 4,
                             "actual_min": a}} for i, a in enumerate(obs)]
               + [{"type": "task.finished", "date": DATE, "ts": f"{DATE}T18:09:00", "source": "sim", "key": "dup",
                   "payload": {"order_id": "o0", "task_id": "t0", "item": "Gyoza", "station": "fryer", "actual_min": 99}}])
    ld = learned_durations(led=led)
    ema = 5.0
    for a in obs[1:]:
        ema = 0.75 * ema + 0.25 * a
    g = ld["by_item"]["Gyoza"]
    assert g["n"] == 3 and g["ema_min"] == round(ema, 2) and g["station"] == "fryer" and g["planned_min"] == 4
    assert ld["by_station"]["fryer"]["n"] == 3 and ld["events"] == 3
    assert learned_durations("2026-11-04", led=led)["by_item"] == {}


def test_past_api(out, built):
    os.environ["GONDOLA_REVIEW_LOOP"] = "0"
    from fastapi.testclient import TestClient
    from gondola.api.app import app
    with TestClient(app) as c:
        s = c.get("/api/past/summary", params={"date": DATE}).json()
        assert s["processed"] == 475 and s["date"] == DATE
        p1 = c.get("/api/past/ledger", params={"date": DATE, "limit": 50}).json()
        assert len(p1["events"]) == 50 and p1["next_before_id"]
        ts = [e["ts"] for e in p1["events"]]
        assert ts == sorted(ts, reverse=True)
        p2 = c.get("/api/past/ledger", params={"date": DATE, "limit": 50, "before_id": p1["next_before_id"]}).json()
        assert not {e["id"] for e in p1["events"]} & {e["id"] for e in p2["events"]}
        assert p2["events"][0]["ts"] <= p1["events"][-1]["ts"]
        t = c.get("/api/past/ledger", params={"date": DATE, "types": "cash.counted,payout.report_arrived"}).json()
        assert {e["type"] for e in t["events"]} == {"cash.counted", "payout.report_arrived"}
        assert c.get("/api/past/ledger", params={"date": "bad"}).status_code == 400
        assert "by_item" in c.get("/api/past/learned").json()
