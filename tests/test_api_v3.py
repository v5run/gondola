"""V3 API tests: live replay SSE, drill-down metrics vs direct pandas, enriched reports, monthly report, backfill.
Contract: docs/app_contract.md ("V3 additions"). Runs a real 5-night backfill (Nov 1-5 2026) into a temp out/."""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient  # noqa: E402

from gondola import backfill, pipeline  # noqa: E402
from gondola.api.app import app  # noqa: E402
from gondola.storage import Bucket  # noqa: E402

DB = ROOT / "data" / "gondola.duckdb"
D = "2026-11-05"
CH = ["in_store", "doordash", "ubereats", "grubhub"]


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
def orders():
    con = duckdb.connect(str(DB), read_only=True)
    o = con.execute("SELECT * FROM orders").df()
    lines = con.execute("SELECT * FROM order_lines").df()
    lab = con.execute("SELECT business_date, SUM(hours*wage) cost FROM labour GROUP BY 1").df()
    con.close()
    return o, lines, lab


@pytest.fixture(scope="module")
def hist(tmp_path_factory):
    """A real 5-night backfill into a temp out/ (reuses the backtest cache if there is one)."""
    out = tmp_path_factory.mktemp("v3") / "out"
    out.mkdir()
    if (ROOT / "out" / "backtest_cache.csv").exists():
        shutil.copy(ROOT / "out" / "backtest_cache.csv", out / "backtest_cache.csv")
    summary = backfill.run(5, end=D, out=out, quiet=True)
    return out, summary


@pytest.fixture(scope="module")
def client(hist):
    out, _ = hist
    old = pipeline.OUT
    pipeline.OUT = out
    with TestClient(app) as c:
        yield c
    pipeline.OUT = old


# ------------------------------------------------------------------ backfill
def test_backfill_small_window(hist):
    out, s = hist
    assert s["nights"] == 5 and s["first"] == "2026-11-01" and s["last"] == D
    assert s["statuses"] == {"done": 5} and s["monthly"] == ["2026-10"]
    state = json.loads((out / "closes.json").read_text(encoding="utf-8"))
    assert sorted(k for k in state if not k.startswith("_")) == [f"2026-11-0{i}" for i in range(1, 6)]
    # each night closed as of 11:10 pm that night on a database cut to that night
    for i in range(1, 6):
        r = json.loads((out / f"close_2026-11-0{i}.json").read_text(encoding="utf-8"))
        assert r["as_of"] == f"2026-11-0{i}T23:10:00" and r["status"] == "done"
        lo = (r["plan"]["portion_counts"] or {}).get("chashu")
        assert lo is not None and 0 <= lo <= 40
        assert not Path(r["db"]).is_absolute()
    assert json.loads((out / f"close_{D}.json").read_text(encoding="utf-8"))["db"] == "data/gondola.duckdb"
    # every card approved except tonight's (the manager approves it in the app)
    ap = json.loads((out / "approvals.json").read_text(encoding="utf-8"))
    assert sorted(ap) == [f"2026-11-0{i}" for i in range(1, 5)]
    for d_, a in ap.items():
        assert a["for_run"] == json.loads((out / f"close_{d_}.json").read_text(encoding="utf-8"))["run_id"]
    b = Bucket(out / "bucket")
    for i in range(1, 6):
        rec = b.index[f"daily/2026-11-0{i}"]
        assert rec["status"] == "stored" and rec["sha256"] and b.path(rec["uri"]).exists() and b.path(rec["html"]).exists()
    m = b.index["monthly/2026-10"]
    assert b.path(m["uri"]).exists() and b.path(m["html"]).exists() and b.monthly_summary("2026-10")["orders"] > 10000
    ob = [json.loads(x) for x in (out / "outbox.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sum(1 for x in ob if x["channel"] == "email") == 5 and all(x["status"] == "dry_run" for x in ob)
    assert not any(out.parent.glob(".out_*")), "staging folders cleaned up"


def test_cut_matches_ingest(tmp_path):
    from gondola.connectors.ingest import cut, ingest
    a = ingest(db_path=tmp_path / "a.duckdb", upto="2026-10-20")
    b = cut("2026-10-20", tmp_path / "b.duckdb")
    ca, cb = duckdb.connect(str(a), read_only=True), duckdb.connect(str(b), read_only=True)
    for (t,) in ca.execute("SHOW TABLES").fetchall():
        x = ca.execute(f"SELECT * FROM {t} ORDER BY ALL").df()
        y = cb.execute(f"SELECT * FROM {t} ORDER BY ALL").df()
        assert x.equals(y), t
    ca.close(); cb.close()


# ------------------------------------------------------------------ live stream
def test_live_stream_to_done(client, orders):
    o = orders[0]
    ev = read_sse(client, f"/api/live/stream?date={D}&speed=1000000&from=11:00")
    names = [n for n, _ in ev]
    assert names[0] == "start" and names[-1] == "done"
    day = o[o.business_date == pd.Timestamp(D)]
    done = ev[-1][1]
    comp = day[day.status == "completed"]
    assert done["orders"] == len(comp) == 475 and done["net_sales"] == round(comp.subtotal.sum(), 2) == 14964.0
    assert done["placed"] == len(day) and done["cancels"] == int((day.status == "cancelled").sum())
    assert done["by_channel"] == {c: int((comp.channel == c).sum()) for c in CH}
    od = [p for n, p in ev if n == "order"]
    assert len(od) == len(day) and {x["id"] for x in od} == set(day.order_id)
    assert all(set(x) >= {"t", "id", "channel", "items", "subtotal", "status"} and x["items"] for x in od)
    ticks = [p for n, p in ev if n == "tick"]
    assert ticks[0]["t"] == "11:00" and ticks[-1]["t"] == "22:00" and len(ticks) == 11 * 60 + 1
    for tk in (ticks[300], ticks[-1]):  # running totals = everything placed before the minute
        cut = pd.Timestamp(f"{D} {tk['t']}")
        c = comp[comp.created_at < cut]
        assert tk["orders"] == len(c) and abs(tk["net_sales"] - c.subtotal.sum()) < 0.01
        assert tk["by_channel"] == {ch: int((c.channel == ch).sum()) for ch in CH}
        assert tk["cancels"] == int(((day.status == "cancelled") & (day.created_at < cut)).sum())
    assert ticks[0]["chashu_left"] == 479 and ticks[-1]["chashu_left"] == 0
    kinds = [p["kind"] for n, p in ev if n == "event"]
    assert {"sold_out", "rush_start", "rush_end"} <= set(kinds) and kinds.count("pause") == 3
    so = next(p for n, p in ev if n == "event" and p["kind"] == "sold_out")
    assert so["t"] == "20:39" and done["sold_out_at"] == "20:39"
    seq = [p["t"][:5] for n, p in ev if n in ("order", "tick", "event")]
    assert seq == sorted(seq), "events stream in time order"


def test_live_stream_from_and_errors(client):
    ev = read_sse(client, f"/api/live/stream?date={D}&speed=1000000&from=21:30")
    ticks = [p for n, p in ev if n == "tick"]
    assert ticks[0]["t"] == "21:30" and ticks[0]["orders"] > 400  # earlier service is carried in the totals
    assert all(p["t"] >= "21:30:00" for n, p in ev if n == "order")
    closed = read_sse(client, "/api/live/stream?date=2025-12-25&speed=1000000")
    assert closed[-1][0] == "done" and closed[-1][1]["status"] == "closed"
    assert client.get("/api/live/stream?speed=0").status_code == 400
    assert client.get("/api/live/stream?from=25:00").status_code == 400


# ------------------------------------------------------------------ metrics vs direct pandas
def test_intraday_matches_pandas(client, orders):
    o = orders[0]
    r = client.get("/api/metrics/intraday", params={"date": D}).json()
    assert r["date"] == D and len(r["bins"]) == 48 and r["bins"][0]["time"] == "11:00"
    day = o[(o.business_date == pd.Timestamp(D)) & (o.status == "completed")].copy()
    day["slot"] = day.created_at.dt.hour * 4 + day.created_at.dt.minute // 15
    for b in r["bins"]:
        s = int(b["time"][:2]) * 4 + int(b["time"][3:]) // 15
        x = day[day.slot == s]
        assert b["orders"] == len(x) and abs(b["net_sales"] - x.subtotal.sum()) < 0.01
        assert b["by_channel"] == {c: int((x.channel == c).sum()) for c in CH}
    assert sum(b["orders"] for b in r["bins"]) == 475
    base = r["baseline_dates"]
    assert len(base) >= 3 and len(r["usual"]) == 48
    bo = o[o.business_date.isin(pd.to_datetime(base)) & (o.status == "completed")].copy()
    bo["slot"] = bo.created_at.dt.hour * 4 + bo.created_at.dt.minute // 15
    want = bo.groupby("slot").size() / len(base)
    assert abs(r["usual"][30]["orders"] - want.get(74, 0)) < 0.01  # 18:30


def test_items_match_pandas(client, orders):
    o, lines, _ = orders
    r = client.get("/api/metrics/items", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    c = o[(o.business_date >= "2026-10-01") & (o.business_date <= "2026-10-31") & (o.status == "completed")]
    x = lines[lines.order_id.isin(c.order_id)].groupby("item").agg(sold=("price", "size"), net=("price", "sum"))
    assert len(r) == len(x) and r == sorted(r, key=lambda z: -z["net_sales"])
    for row in r:
        assert row["sold"] == x.loc[row["item"], "sold"] and abs(row["net_sales"] - x.loc[row["item"], "net"]) < 0.01
    assert abs(sum(z["share"] for z in r) - 1) < 0.01


def test_range_matches_pandas(client, orders):
    o, _, lab = orders
    r = client.get("/api/metrics/range", params={"start": "2026-10-01", "end": "2026-10-31"}).json()

    def tot(s, e):
        c = o[(o.business_date >= s) & (o.business_date <= e)]
        return c[c.status == "completed"], c
    comp, allo = tot("2026-10-01", "2026-10-31")
    assert r["days"] == 31 and r["orders"] == len(comp) and abs(r["net_sales"] - comp.subtotal.sum()) < 0.01
    assert r["cancels"] == int((allo.status == "cancelled").sum())
    assert r["avoidable_cancels"] == int((allo.cancel_reason == "item_unavailable").sum())
    assert abs(r["avg_ticket"] - comp.subtotal.sum() / len(comp)) < 0.01
    lc = lab[(lab.business_date >= "2026-10-01") & (lab.business_date <= "2026-10-31")].cost.sum()
    assert abs(r["labour_pct"] - lc / comp.subtotal.sum()) < 0.0001
    assert r["by_channel"] == {c: round(float(comp[comp.channel == c].subtotal.sum()), 2) for c in CH}
    pc, _ = tot("2026-08-31", "2026-09-30")  # the previous 31 days
    assert r["prev"] == {"start": "2026-08-31", "end": "2026-09-30", "net_sales": round(pc.subtotal.sum(), 2), "orders": len(pc)}
    assert abs(r["vs_prev_pct"]["net_sales"] - (comp.subtotal.sum() / pc.subtotal.sum() - 1)) < 0.0001
    assert abs(r["vs_prev_pct"]["orders"] - (len(comp) / len(pc) - 1)) < 0.0001
    by_day = comp.groupby("business_date").subtotal.sum()
    assert r["best_day"]["date"] == str(by_day.idxmax().date()) and r["worst_day"]["date"] == str(by_day.idxmin().date())
    # the first weeks of data have no full previous period
    early = client.get("/api/metrics/range", params={"start": "2025-11-06", "end": "2025-11-12"}).json()
    assert early["vs_prev_pct"] == {"net_sales": None, "orders": None}
    assert client.get("/api/metrics/range", params={"start": "2026-10-10", "end": "2026-10-01"}).status_code == 400


EXPLAIN_KEYS = {"status", "vs_usual", "vs_similar", "drivers", "context", "items_up", "items_down"}


def test_day_explain(client, orders):
    import time
    o, lines, _ = orders
    ex = client.get(f"/api/day/{D}").json()["explain"]
    assert EXPLAIN_KEYS <= set(ex) and ex["status"] == "ok"
    base = ex["vs_usual"]["baseline_dates"]
    assert base == ["2026-10-08", "2026-10-15", "2026-10-22", "2026-10-29"] and ex["vs_usual"]["net_sales_pct"] == -0.0443
    assert ex["vs_usual"]["orders_pct"] == -0.0114
    assert len(ex["vs_similar"]["dates"]) == 5 and ex["vs_similar"]["net_sales_pct"] is not None
    assert {r["key"] for r in ex["drivers"]["channel"]} == set(CH) and {r["key"] for r in ex["drivers"]["daypart"]} == {"lunch", "dinner", "late"}
    for r in ex["drivers"]["channel"]:
        assert set(r) == {"key", "today", "usual", "change"} and abs(r["today"] - r["usual"] - r["change"]) < 0.02
    ins = next(r for r in ex["drivers"]["channel"] if r["key"] == "in_store")
    t = o[(o.business_date == pd.Timestamp(D)) & (o.status == "completed") & (o.channel == "in_store")].subtotal.sum()
    assert abs(ins["today"] - t) < 0.01
    c = ex["context"]
    assert c["rain"] is True and c["snow"] is False and isinstance(c["temp_high_c"], float) and "Penguins home game" in c["events"]
    # items: units vs the average of the same baseline days, top 3 by unit change
    comp = o[o.status == "completed"]
    lt = lines[lines.order_id.isin(comp[comp.business_date == pd.Timestamp(D)].order_id)].item.value_counts()
    lb = lines[lines.order_id.isin(comp[comp.business_date.isin(pd.to_datetime(base))].order_id)].item.value_counts() / 4
    ch = lt.reindex(lt.index.union(lb.index), fill_value=0) - lb.reindex(lt.index.union(lb.index), fill_value=0)
    assert len(ex["items_up"]) == 3 and len(ex["items_down"]) == 3
    assert ex["items_up"][0]["item"] == ch.idxmax() and abs(ex["items_up"][0]["change"] - ch.max()) < 0.01
    assert ex["items_down"][0]["item"] == ch.idxmin() and abs(ex["items_down"][0]["change"] - ch.min()) < 0.01
    assert all(r["change"] > 0 for r in ex["items_up"]) and all(r["change"] < 0 for r in ex["items_down"])
    closed = client.get("/api/day/2025-12-25").json()["explain"]
    assert EXPLAIN_KEYS <= set(closed) and closed["status"] == "closed" and closed["context"]["events"] == ["Christmas (closed)"]
    assert closed["items_up"] == [] and closed["drivers"] == {"channel": [], "daypart": []}
    t0 = time.perf_counter()
    client.get(f"/api/day/{D}")
    assert time.perf_counter() - t0 < 0.3, "warm /day must be fast"


def test_range_explain(client, orders):
    o = orders[0]
    r = client.get("/api/metrics/range", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    ex = r["explain"]
    assert EXPLAIN_KEYS <= set(ex) and ex["status"] == "ok"
    assert ex["vs_usual"]["net_sales_pct"] == r["vs_prev_pct"]["net_sales"] and ex["vs_usual"]["orders_pct"] == r["vs_prev_pct"]["orders"]
    assert ex["vs_usual"]["baseline_dates"][0] == "2026-08-31" and len(ex["vs_usual"]["baseline_dates"]) == 31
    assert ex["vs_similar"] == {"net_sales_pct": None, "dates": []}
    dd = next(x for x in ex["drivers"]["channel"] if x["key"] == "doordash")
    prev = o[(o.business_date >= "2026-08-31") & (o.business_date <= "2026-09-30") & (o.status == "completed") & (o.channel == "doordash")]
    assert dd["today"] == r["by_channel"]["doordash"] and abs(dd["usual"] - prev.subtotal.sum()) < 0.01
    assert ex["context"]["rain"] is True and ex["context"]["rain_days"] >= 1 and any("Penguins" in e for e in ex["context"]["events"])
    assert len(ex["items_up"]) == 3
    early = client.get("/api/metrics/range", params={"start": "2025-11-06", "end": "2025-11-12"}).json()["explain"]
    assert early["status"] == "no_baseline" and early["items_up"] == []


def test_day_detail(client):
    r = client.get(f"/api/day/{D}").json()
    assert r["overview"]["kpis"]["orders"] == 475 and r["overview"]["last_close"]["date"] == D
    assert r["close"]["date"] == D and r["close"]["approved"] is False and r["close"]["card"]
    assert r["report"] == {"status": "stored", "url_html": f"/api/reports/{D}.html", "url_pdf": f"/api/reports/{D}.pdf"}
    prev = client.get("/api/day/2026-11-04").json()
    assert prev["close"]["approved"] is True
    old = client.get("/api/day/2026-06-10").json()
    assert old["close"] is None and old["report"] is None and old["overview"]["kpis"]["orders"] > 0


# ------------------------------------------------------------------ reports
def test_reports_enriched(client, hist):
    out, _ = hist
    r = client.get("/api/reports").json()
    assert [(x["kind"], x["date"]) for x in r] == [("daily", "2026-11-05"), ("daily", "2026-11-04"), ("daily", "2026-11-03"),
                                                   ("daily", "2026-11-02"), ("monthly", "2026-10"), ("daily", "2026-11-01")]
    keys = {"date", "kind", "status", "url_html", "url_pdf", "headline", "net_sales", "orders", "vs_usual_pct", "urgent",
            "texted", "recoverable_usd"}
    for x in r:
        assert keys <= set(x) and x["status"] == "stored" and x["headline"]
    t = r[0]
    close = json.loads((out / f"close_{D}.json").read_text(encoding="utf-8"))
    assert t["net_sales"] == 14964.0 and t["orders"] == 475
    assert t["vs_usual_pct"] == close["analyst"]["compare"]["net_sales"]["change_pct"]
    assert t["urgent"] == 3 and t["texted"] is True
    assert t["recoverable_usd"] == round(sum(f["recoverable_usd"] for f in close["findings"] if f["kind"] == "payout_short"), 2)
    assert t["url_pdf"] == f"/api/reports/{D}.pdf" and t["url_html"] == f"/api/reports/{D}.html"
    m = next(x for x in r if x["kind"] == "monthly")
    assert m["url_pdf"] == "/api/reports/monthly/2026-10.pdf" and "October" in m["headline"] and m["orders"] > 10000


def test_monthly_report_renders(client):
    h = client.get("/api/reports/monthly/2026-10.html")
    assert h.status_code == 200 and h.text.count('class="page"') == 2
    for s in ("October 2026", "Net sales by day", "Forecast accuracy", "Best day", "Worst day", "<svg"):
        assert s in h.text
    p = client.get("/api/reports/monthly/2026-10.pdf")
    assert p.status_code == 200 and p.content[:4] == b"%PDF"
    import io
    import pypdf
    assert len(pypdf.PdfReader(io.BytesIO(p.content)).pages) == 2
    assert client.get("/api/reports/monthly/2026-13.pdf").status_code == 400
    assert client.get("/api/reports/monthly/2024-01.html").status_code == 404


def test_expired_daily_rebuilds_on_request(client, hist):
    out, _ = hist
    b = Bucket(out / "bucket")
    b.apply_lifecycle(datetime(2026, 12, 3, 23, 0))  # Nov 1-2 are 30+ days old; Nov 3 is 29 d 23 h 50 min
    st = {x["date"]: x["status"] for x in client.get("/api/reports").json() if x["kind"] == "daily"}
    assert st["2026-11-01"] == "expired" and st[D] == "stored"
    old = next(x for x in client.get("/api/reports").json() if x["date"] == "2026-11-01")
    assert old["headline"] and old["net_sales"] > 0  # facts survive expiry (findings.json is kept)
    p = client.get("/api/reports/2026-11-01.pdf")
    assert p.status_code == 200 and p.content[:4] == b"%PDF"
    h = client.get("/api/reports/2026-11-02.html")
    assert h.status_code == 200 and "rebuilt" in h.text
    st = {x["date"]: x["status"] for x in client.get("/api/reports").json() if x["kind"] == "daily"}
    assert st["2026-11-01"] == "rebuilt" and st["2026-11-02"] == "rebuilt" and st["2026-11-03"] == "stored"
    assert client.get("/api/reports/2026-01-01.pdf").status_code == 404
