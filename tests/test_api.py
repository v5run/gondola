"""API tests (FastAPI TestClient). Contract: docs/app_contract.md."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient  # noqa: E402

from gondola import pipeline  # noqa: E402
from gondola.api.app import app  # noqa: E402


def read_sse(client, url):
    events, name = [], None
    with client.stream("GET", url) as s:
        assert s.status_code == 200
        assert s.headers["content-type"].startswith("text/event-stream")
        for line in s.iter_lines():
            if line.startswith("event:"):
                name = line[7:].strip()
            elif line.startswith("data:"):
                events.append((name, json.loads(line[6:])))
    return events


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    old = pipeline.OUT
    pipeline.OUT = out
    with TestClient(app) as c:
        yield c
    pipeline.OUT = old


@pytest.fixture(scope="module")
def closed(client):
    r = client.post("/api/close", json={"date": "2026-11-05", "portion_counts": {"chashu": 0}})
    assert r.status_code == 200
    ev = read_sse(client, f"/api/close/{r.json()['run_id']}/events")
    return ev


def test_health_store_integrations(client):
    assert client.get("/api/health").json()["ok"] is True
    s = client.get("/api/store").json()
    assert s["today"] == "2026-11-05" and s["tomorrow"] == "2026-11-06" and s["limited_items"] == ["Chashu"]
    i = client.get("/api/integrations").json()
    for k in ("twilio", "sendgrid", "llm", "square", "doordash"):
        assert "live" in i[k]


def test_overview_and_metrics(client):
    o = client.get("/api/overview").json()
    assert o["kpis"]["orders"] == 475 and o["kpis"]["net_sales"] == 14964.0
    assert o["context"]["rain"] is True and len(o["curve_today"]) == len(o["curve_usual"]) == 48
    closed = client.get("/api/overview", params={"date": "2025-12-25"}).json()
    assert closed["closed"] is True
    m = client.get("/api/metrics/daily", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    assert len(m) == 31 and {"date", "orders", "net_sales"} <= set(m[0])
    assert client.get("/api/overview", params={"date": "not-a-date"}).status_code == 400


def test_forecast(client):
    f = client.get("/api/forecast").json()
    assert f["date"] == "2026-11-06" and f["p10"] <= f["p50"] <= f["p90"]
    assert f["curve"] and f["similar_days"] and "start" in f["rush"]


def test_close_stream(closed):
    names = [n for n, _ in closed]
    assert names[-1] == "done" and closed[-1][1]["status"] == "done"
    steps = {p["step"] for n, p in closed if n == "step" and p["status"] == "done"}
    assert {"books", "stock", "demand", "analyst", "plan", "sentinel", "report", "guard"} <= steps
    urgent = [p for n, p in closed if n == "finding" and p["urgency"] == "urgent"]
    assert len(urgent) == 3


def test_second_tap_replays_existing(client, closed):
    r = client.post("/api/close", json={"date": "2026-11-05"}).json()
    ev = read_sse(client, f"/api/close/{r['run_id']}/events")
    assert ev[-1][0] == "done" and ev[-1][1]["idempotent"] is True


def test_closes_detail_and_approve(client, closed):
    lst = client.get("/api/closes").json()
    assert lst[0]["date"] == "2026-11-05" and lst[0]["urgent_count"] == 3
    d = client.get("/api/closes/2026-11-05").json()
    assert d["card"][0]["item"] == "Chashu" and d["card"][0]["prep"] > 0
    assert d["disputes"] and all("days_left" in x for x in d["disputes"])
    assert d["books"]["cash"]["difference"] == -23.5 and d["approved"] is False
    card = d["card"]; card[0]["prep"] = 700
    a = client.post("/api/closes/2026-11-05/approve", json={"card": card}).json()
    assert a["approved"] and a["card"][0]["prep"] == 700
    assert client.get("/api/closes/2026-11-05").json()["approved"] is True
    bad = [{**card[0], "prep": -5}]
    assert client.post("/api/closes/2026-11-05/approve", json={"card": bad}).status_code == 400
    assert client.get("/api/closes/2026-01-01").status_code == 404


def test_reports(client, closed):
    r = client.get("/api/reports").json()
    assert any(x["date"] == "2026-11-05" for x in r)
    pdf = client.get("/api/reports/2026-11-05.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert client.get("/api/reports/2026-11-05.html").status_code == 200
    assert client.get("/api/reports/2026-01-01.pdf").status_code == 404


@pytest.mark.parametrize("q,clarify", [("DoorDash sales last week?", False), ("uber vs doordash last month", False),
                                       ("what's the forecast for tomorrow", False), ("asdf", True)])
def test_ask(client, q, clarify):
    a = client.post("/api/ask", json={"question": q}).json()
    assert a["text"] and a["clarify"] is clarify
    if not clarify:
        assert a["chart"] is not None
    assert client.post("/api/ask", json={"question": ""}).status_code == 400


def test_sms_inbound_and_outbox(client, closed):
    r = client.post("/api/sms/inbound", data={"From": "+14125550142", "Body": "1"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert "<Response><Message>" in r.text and "23.50" in r.text
    r2 = client.post("/api/sms/inbound", data={"From": "+14125550142", "Body": "sales yesterday"})
    assert "Net sales" in r2.text
    ob = client.get("/api/outbox").json()
    assert ob[0]["direction"] == "out" and any(x["direction"] == "in" for x in ob)
    assert any(x["channel"] == "sms" and "need" in (x["body"] or "") for x in ob)  # the bundled close text


def test_guard_replay_with_recount(client):
    r = client.post("/api/guard/replay", json={"speed": 1e6, "count_error": 0.05, "recount": True}).json()
    ev = read_sse(client, f"/api/guard/{r['run_id']}/events")
    names = [n for n, _ in ev]
    assert names[0] == "start" and names[-1] == "done"
    assert "recount_prompt" in names and names.count("pause") == 3
    done = ev[-1][1]
    assert done["cancels"] < done["status_quo_cancels"]
    tick = [p for n, p in ev if n == "tick"][0]
    assert set(tick["available"]) == {"in_store", "doordash", "ubereats", "grubhub"}


def test_guard_manager_recount(client):
    r = client.post("/api/guard/replay", json={"speed": 3000, "count_error": 0.1, "recount": True}).json()
    rid = r["run_id"]
    import time
    from gondola.api.runs import RUNS
    for _ in range(400):
        if any(n == "recount_prompt" for n, _ in RUNS[rid].events):
            break
        time.sleep(0.01)
    assert client.post(f"/api/guard/{rid}/recount", json={"count": 90}).json()["ok"]
    assert client.post(f"/api/guard/{rid}/recount", json={"count": "x"}).status_code == 400
    ev = read_sse(client, f"/api/guard/{rid}/events")
    rd = [p for n, p in ev if n == "recount_done"]
    assert rd and rd[0]["source"] == "manager" and rd[0]["count"] == 90
    assert client.get("/api/guard/nope/events").status_code == 404


def test_stored_json_has_no_absolute_paths(client, closed):
    """out/ must move between machines (container <-> Windows): no absolute paths in closes, outbox or the bucket index."""
    import re as _re
    out = pipeline.OUT
    files = [out / "closes.json", out / "outbox.jsonl", out / "close_2026-11-05.json",
             out / "bucket" / "stores" / "hanabi-sqh" / "index.json"]
    for f in files:
        assert f.exists(), f
        txt = f.read_text(encoding="utf-8")
        assert str(ROOT) not in txt and str(out) not in txt, f
        assert not _re.search(r'"(/|[A-Za-z]:\\\\)[^"]*\.(pdf|json|duckdb)"', txt), f
    email = [x for x in client.get("/api/outbox").json() if x["channel"] == "email"]
    assert email and email[-1]["attachment"] == "2026-11-05.pdf" and email[-1]["attachment_url"] == "/api/reports/2026-11-05.pdf"
    assert client.get(email[-1]["attachment_url"]).content[:4] == b"%PDF"


def test_sellout_question_api_and_sms(client, closed):
    a = client.post("/api/ask", json={"question": "Why did we run out of chashu tonight?"}).json()
    assert not a["clarify"] and "sold out at 8:39 pm" in a["text"] and "12 app orders" in a["text"]
    assert "Tomorrow's card: make" in a["text"]
    r = client.post("/api/sms/inbound", data={"From": "+14125550142", "Body": "why did we run out of chashu?"})
    assert "sold out at 8:39 pm" in r.text and "Which day" not in r.text


def test_disputes_have_date_and_items(client, closed):
    d = client.get("/api/closes/2026-11-05").json()
    x = d["disputes"][0]
    assert x["date"] == x["for_date"] and isinstance(x["items"], list) and x["items"]


def test_forced_rerun_clears_approval_and_suppressed_alerts_keep_original(client, closed):
    assert client.post("/api/closes/2026-11-05/approve", json={}).json()["approved"]
    assert client.get("/api/closes/2026-11-05").json()["approved"] is True
    r = client.post("/api/close", json={"date": "2026-11-05", "force": True, "portion_counts": {"chashu": 30}}).json()
    ev = read_sse(client, f"/api/close/{r['run_id']}/events")
    assert ev[-1][1]["status"] == "done"
    d = client.get("/api/closes/2026-11-05").json()
    assert d["approved"] is False and d["card"][0]["on_hand"] == 30  # the new plan's card, not the old approved one
    sup = [x for x in d["alerts"] if x["status"] == "duplicate_suppressed"]
    assert sup and all(x["sent_at"] and x["body"] for x in sup)
    ob = client.get("/api/outbox").json()
    assert [x["ts"] for x in ob] == sorted((x["ts"] for x in ob), reverse=True)
