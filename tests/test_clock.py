"""The store clock (gondola/now.py): /api/now, today cut at now across the endpoints, close locked until close time,
live stream catch-up. Each test freezes the clock with GONDOLA_NOW + GONDOLA_CLOCK=frozen."""
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient  # noqa: E402

from gondola import now  # noqa: E402
from gondola.api.app import app  # noqa: E402

DB = ROOT / "data" / "gondola.duckdb"
D = "2026-11-05"  # a Thursday: open 11:00-22:00


@pytest.fixture(scope="module")
def day():
    con = duckdb.connect(str(DB), read_only=True)
    o = con.execute("SELECT * FROM orders WHERE business_date = ?", [D]).df()
    con.close()
    return o


@pytest.fixture
def at(monkeypatch):
    def set_(ts: str):
        monkeypatch.setenv("GONDOLA_NOW", ts)
        monkeypatch.setenv("GONDOLA_CLOCK", "frozen")
        return TestClient(app)
    return set_


def test_now_endpoint(at):
    c = at(f"{D}T19:30:00")
    n = c.get("/api/now").json()
    assert n == {**n, "today": D, "now": "19:30:00", "tz": "America/New_York", "mapped": False, "phase": "open",
                 "cutoff": "19:30", "open": "11:00", "close": "22:00"}
    assert c.get("/api/store").json()["today"] == D
    # a business date past the data shows the latest data day, complete and closed (never a time-of-day cut)
    n = at("2031-03-14T08:15:42").get("/api/now").json()
    assert n["today"] == D and n["mapped"] is True and n["now"] == "08:15:42" and n["phase"] == "closed" and n["cutoff"] is None
    assert at(f"{D}T23:30:00").get("/api/now").json()["phase"] == "closed"
    # the business day runs to 4 a.m.: 1:41 am Friday is still Thursday, closed
    n = at("2026-11-06T01:41:00").get("/api/now").json()
    assert n["today"] == D and n["business_date"] == D and not n["mapped"] and n["phase"] == "closed" and n["cutoff"] is None
    ov = at("2026-11-06T01:41:00").get("/api/overview").json()
    assert ov["date"] == D and not ov["closed"] and ov["as_of"] is None and len(ov["curve_today"]) == 48
    # 4 a.m. on: Friday's business day, past the data -> latest data day, closed
    n = at("2026-11-06T04:00:00").get("/api/now").json()
    assert n["today"] == D and n["business_date"] == "2026-11-06" and n["mapped"] and n["phase"] == "closed"


def test_clock_runs_from_gondola_now(monkeypatch):
    monkeypatch.setenv("GONDOLA_NOW", f"{D}T19:30:00")
    monkeypatch.delenv("GONDOLA_CLOCK", raising=False)
    now._ANCHOR.clear()
    t = now.wall()
    assert t >= pd.Timestamp(f"{D} 19:30:00") and t < pd.Timestamp(f"{D} 19:31:00")


def test_today_cut_at_now(at, day):
    c = at(f"{D}T19:30:00")
    before = day[day.created_at < pd.Timestamp(f"{D} 19:30:00")]
    done = before[before.status == "completed"]
    ov = c.get("/api/overview").json()
    assert ov["date"] == D and ov["as_of"] == "19:30" and not ov["closed"]
    assert ov["kpis"]["orders"] == len(done)
    assert ov["kpis"]["net_sales"] == pytest.approx(done.subtotal.sum(), abs=0.01)
    assert ov["curve_today"][-1]["time"] == "19:15"  # bins after now are absent, not zero
    intra = c.get(f"/api/metrics/intraday?date={D}").json()
    assert intra["as_of"] == "19:30" and intra["bins"][-1]["time"] == "19:15"
    assert sum(b["orders"] for b in intra["bins"]) == len(done)
    assert [b["time"] for b in intra["usual"]][-1] == "22:45"  # the usual curve is the whole day
    daily = c.get(f"/api/metrics/daily?start={D}&end={D}").json()
    assert daily[0]["orders"] == len(done)
    rng = c.get(f"/api/metrics/range?start={D}&end={D}").json()
    assert rng["orders"] == len(done)
    items = c.get(f"/api/metrics/items?start={D}&end={D}").json()
    assert sum(i["net_sales"] for i in items) == pytest.approx(done.subtotal.sum(), abs=0.05)
    dd = c.get(f"/api/day/{D}").json()
    assert dd["overview"]["kpis"]["orders"] == len(done)
    # an earlier day is untouched by the clock
    prev = c.get("/api/overview?date=2026-11-04").json()
    assert prev["kpis"]["orders"] == at(f"{D}T23:30:00").get("/api/overview?date=2026-11-04").json()["kpis"]["orders"]


def test_before_open_and_after_close(at, day):
    ov = at(f"{D}T09:00:00").get("/api/overview").json()
    assert ov["closed"] and ov["not_open_yet"] and ov["opens"] == "11:00" and ov["curve_today"] == []
    assert at(f"{D}T09:00:00").get("/api/metrics/intraday").json()["bins"] == []
    c = at(f"{D}T23:30:00")
    ov = c.get("/api/overview").json()
    assert ov["kpis"]["orders"] == int((day.status == "completed").sum()) and ov["as_of"] is None
    assert len(ov["curve_today"]) == 48


def test_close_locked_until_close_time(at):
    r = at(f"{D}T19:30:00").post("/api/close", json={"date": D})
    assert r.status_code == 409 and "10:00 pm" in r.json()["detail"]
    assert at(f"{D}T19:30:00").post("/api/close", json={"date": "2026-11-06"}).status_code == 400


def test_live_stream_catchup(at, day):
    c = at(f"{D}T19:30:00")
    ev, name = [], None
    with c.stream("GET", f"/api/live/stream?date={D}&speed=1000000&from=19:30:00&catchup=1") as s:
        for line in s.iter_lines():
            if line.startswith("event:"):
                name = line[7:].strip()
            elif line.startswith("data:"):
                ev.append((name, json.loads(line[6:])))
    cut = pd.Timestamp(f"{D} 19:30:00")
    caught = [d for n, d in ev if n == "order" and d.get("catchup")]
    later = [d for n, d in ev if n == "order" and not d.get("catchup")]
    assert len(caught) == int((day.created_at < cut).sum())
    assert len(later) == int((day.created_at >= cut).sum())
    assert all(d["t"] >= "19:30:00" for d in later) and all(d["t"] < "19:30:00" for d in caught)
    assert ev[0][0] == "start" and ev[0][1]["catchup"] is True and ev[-1][0] == "done"
