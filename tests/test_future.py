"""Future: nowcast (arrivals contract, shrinkage, no data after now), drivers vs pandas, limited items (config from
recipes, runout, pause ordering, tomorrow's cards) and the /api/future endpoints. Offline: no model, no network."""
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for k in ("GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "GONDOLA_AGENTS", "GONDOLA_WEATHER"):
    os.environ.pop(k, None)

from gondola.future import base as B, drivers as DR, horizon as H, items as IT, nowcast as N  # noqa: E402
from gondola.tools import plan  # noqa: E402

D = "2026-11-05"
AT = datetime(2026, 11, 5, 19, 30)
KEYS = {"time", "channel", "p10", "p50", "p90"}


@pytest.fixture(scope="module", autouse=True)
def future_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("future")
    old = {k: os.environ.get(k) for k in ("GONDOLA_FUTURE_DIR", "GONDOLA_LEDGER_DB")}
    os.environ["GONDOLA_FUTURE_DIR"] = str(tmp / "future")
    os.environ["GONDOLA_LEDGER_DB"] = str(tmp / "ledger.sqlite")
    yield tmp
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---------------------------------------------------------------- nowcast
def test_arrivals_contract_and_ledger():
    a = N.arrivals(D, AT)
    assert a and all(set(r) == KEYS for r in a)
    assert {r["channel"] for r in a} == set(B.CHANNELS)
    assert min(r["time"] for r in a) == "19:30" and max(r["time"] for r in a) == "21:45"  # Thursday closes at 22:00
    assert len(a) == len({(r["time"], r["channel"]) for r in a}) == 10 * 4
    assert all(0 <= r["p10"] <= r["p50"] <= r["p90"] for r in a)
    assert N.arrivals(D, datetime(2026, 11, 5, 23, 30)) == []  # closed
    from gondola.ledger import ledger
    ev = ledger().query(D, ["forecast.issued"])
    assert [e.key for e in ev] == [f"forecast.issued:rest_of_day:{D}:19:30"]
    N.arrivals(D, datetime(2026, 11, 5, 19, 40))  # same 15-min bin: idempotent
    assert len(ledger().query(D, ["forecast.issued"])) == 1
    assert ev[0].payload["horizon"] == "rest_of_day" and set(ev[0].payload["total"]) == {"p10", "p50", "p90"}


def _base(level=10.0):
    bins = list(range(44, 88))
    return pd.DataFrame([{"bin": b, "channel": c, "p50": level / 4} for b in bins for c in B.CHANNELS])


def _act(base, m, scale, slow=()):
    a = base[base.bin * 15 < m].copy()
    a["n"] = a.p50 * scale * np.where(a.bin.isin(slow), 0.0, 1.0)
    return a[["bin", "channel", "n"]]


def test_shrinkage_grows_with_evidence_and_is_capped():
    base = _base()
    early = N.correction(base, _act(base, 11 * 60 + 30, 0.6), 11 * 60 + 30)
    late = N.correction(base, _act(base, 19 * 60, 0.6), 19 * 60)
    assert early["raw_ratio"] == pytest.approx(0.6) and late["raw_ratio"] == pytest.approx(0.6)
    assert 0 < early["weight"] < late["weight"] <= N.W_MAX
    assert 1 > early["ratio"] > late["ratio"] >= 1 + N.W_MAX * (0.6 - 1) - 1e-9
    none = N.correction(base, _act(base, 11 * 60, 1.0), 11 * 60)  # at opening: no evidence, no change
    assert none["ratio"] == 1.0 and none["weight"] == 0.0


def test_one_slow_half_hour_does_not_swing_the_evening():
    base = _base()
    m = 18 * 60
    normal = N.correction(base, _act(base, m, 1.0), m)
    slow = N.correction(base, _act(base, m, 1.0, slow=(70, 71)), m)  # 17:30-18:00 had no orders at all
    assert normal["ratio"] == pytest.approx(1.0)
    assert 0.96 < slow["ratio"] < 1.0
    rb = N.rest_bins(base, m, slow["factor"])
    assert rb.p50.sum() / N.rest_bins(base, m, normal["factor"]).p50.sum() > 0.96


def test_nowcast_uses_no_data_after_now(tmp_path):
    """Delete every order of the day after 19:30 in a copy of the store: the 19:30 nowcast and runout can't change."""
    db = tmp_path / "cut.duckdb"
    shutil.copy(B.DB, db)
    con = duckdb.connect(str(db))
    con.execute("DELETE FROM order_lines WHERE order_id IN (SELECT order_id FROM orders WHERE business_date = ? "
                "AND created_at >= TIMESTAMP '2026-11-05 19:30:00')", [D])
    con.execute("DELETE FROM orders WHERE business_date = ? AND created_at >= TIMESTAMP '2026-11-05 19:30:00'", [D])
    con.execute("DELETE FROM prep_log WHERE business_date > ?", [D])
    con.close()
    a1, a2 = N.arrivals(D, AT, issue=False), N.arrivals(D, AT, db=db, issue=False)
    assert a1 == a2
    t1, t2 = N.today_view(D, AT), N.today_view(D, AT, db=db)
    assert t1["so_far"] == t2["so_far"] and t1["rest"] == t2["rest"]
    assert [{k: r[k] for k in ("key", "believed_left", "projected_runout", "pause_at")} for r in IT.runout(D, AT)] == \
           [{k: r[k] for k in ("key", "believed_left", "projected_runout", "pause_at")} for r in IT.runout(D, AT, db=db)]


def test_today_view_numbers_add_up():
    v = N.today_view(D, AT)
    assert v["now"] == "19:30" and not v["closed"]
    assert v["so_far"]["orders"] == sum(r.get("actual", 0) for r in v["bins"])
    assert v["expected"]["p50"] == pytest.approx(v["so_far"]["orders"] + v["rest"]["p50"], abs=0.11)
    assert v["rest"]["p10"] <= v["rest"]["p50"] <= v["rest"]["p90"]
    assert sum(r["p50"] for r in N.arrivals(D, AT, issue=False)) == pytest.approx(v["rest"]["p50"], abs=0.5)
    st = B.store_at(D, 19 * 60 + 30)
    n = st.df("SELECT COUNT(*) n FROM orders WHERE business_date = ? AND status = 'completed'", [D]).n[0]
    assert v["so_far"]["orders"] == n


# ---------------------------------------------------------------- drivers
def test_measure_matches_pandas_on_crafted_days():
    days = pd.date_range("2026-01-01", periods=140, freq="D")
    df = pd.DataFrame({"business_date": days, "dow": days.dayofweek, "orders": 100.0 + days.dayofweek * 10})
    rain = (days.day % 5 == 0)
    df.loc[rain, "orders"] *= 1.2
    df["rain"] = rain
    m = DR.measure(df, df.rain, 3)
    thu = df[df.dow == 3]
    want = thu[thu.rain].orders.mean() / thu[~thu.rain].orders.mean() - 1
    assert not m["estimate"] and m["n"] == int(thu.rain.sum()) >= 3
    assert m["effect"] == pytest.approx(want) == pytest.approx(0.2)
    few = df.assign(rain=False)
    few.loc[few.index[[3, 40]], "rain"] = True  # 2 examples: estimate, relative to each weekday's normal
    m2 = DR.measure(few, few.rain, 3)
    normal = few[~few.rain].groupby("dow").orders.mean()
    w = few[few.rain]
    assert m2["estimate"] and m2["n"] == 2
    assert m2["effect"] == pytest.approx((w.orders / w.dow.map(normal)).mean() - 1)
    assert DR.measure(df.assign(rain=False), df.rain & False, 3)["effect"] is None


def test_drivers_for_a_rainy_penguins_thursday_match_pandas():
    drv = DR.drivers(D)
    assert [abs(x["effect_pct"]) for x in drv] == sorted((abs(x["effect_pct"]) for x in drv), reverse=True)
    for x in drv:
        assert {"kind", "label", "time", "window", "effect_pct", "channel_note", "why", "estimate"} <= set(x)
        assert x["kind"] in {"game", "event", "weather", "holiday", "school", "promo", "weekday", "trend"}
    df = B.daily()
    d = pd.Timestamp(D)
    h = df[(df.business_date < d) & (df.business_date >= d - pd.Timedelta(days=365)) & (df.orders > 0) & (df.holiday_factor == 1)]
    h = h.assign(dow=h.business_date.dt.dayofweek)
    thu = h[h.dow == 3]
    rain = next(x for x in drv if x["kind"] == "weather")
    wet, dry = thu[thu.rain.astype(bool)], thu[~thu.rain.astype(bool) & ~thu.snow.astype(bool)]
    assert rain["effect_pct"] == round(100 * (wet.orders.mean() / dry.orders.mean() - 1), 1)
    assert rain["examples"] == len(wet) and not rain["estimate"]
    game = next(x for x in drv if x["kind"] == "game")
    ev = DR._events()
    ev = ev[(ev.date < d) & (ev.date >= d - pd.Timedelta(days=365))]
    pens = thu.business_date.isin(ev[ev.event.str.startswith("Penguins")].date)
    free = ~thu.business_date.isin(ev.date)
    assert game["effect_pct"] == round(100 * (thu[pens].orders.mean() / thu[free & ~pens].orders.mean() - 1), 1)
    assert game["time"] == "19:00" and game["window"] == {"start": "18:30", "end": "21:30"}
    assert game["estimate"] is (int(pens.sum()) < 3)


def test_drivers_never_see_the_day_or_later():
    a = DR.drivers(D)
    b = DR.drivers(D, now=AT)
    assert a == b  # history stops before the date either way
    assert all(e < D for x in a for e in x["evidence"])


# ---------------------------------------------------------------- items
def test_limited_items_config_comes_from_recipes():
    cfg = {x["key"]: x for x in IT.limited_items()}
    assert list(cfg) == ["chashu", "ajitama_egg", "gyoza", "tonkotsu_broth"]
    rec = pd.read_csv(ROOT / "data" / "raw" / "recipes.csv")
    for k, c in cfg.items():
        r = rec[rec.sku == k]
        assert c["used_by"] == dict(zip(r.item, r.qty.astype(float)))
        assert {"key", "name", "sku", "unit", "used_by", "batch", "hold_days", "recount_at", "buffer"} <= set(c)
    assert cfg["tonkotsu_broth"]["unit"] == "L" and cfg["gyoza"]["used_by"] == {"Gyoza": 6.0}
    assert cfg["chashu"]["used_by"]["Chashu Don"] == 1.5 and cfg["chashu"]["hold_days"] == 3


def test_runout_today_and_pause_ordering():
    r = {x["key"]: x for x in IT.runout(D, AT)}
    assert set(r) == set(IT.KEYS)
    st = B.store_at(D, 19 * 60 + 30)
    ch = r["chashu"]
    sold = st.df("""SELECT SUM(m.chashu_portions) s FROM orders o JOIN order_lines l USING(order_id) JOIN menu m ON m.item = l.item
                    WHERE o.business_date = ? AND o.status = 'completed'""", [D]).s[0]
    assert ch["prep"] == 479 and ch["prep_source"] == "prep_log"
    assert ch["believed_left"] == pytest.approx(479 - sold, abs=0.05)
    assert ch["projected_runout"] is not None  # chashu really sold out that night
    order = lambda t: t or "99:99"  # noqa: E731  None = never
    for x in r.values():
        p = x["pause_at"]
        assert set(p) == {"doordash", "ubereats", "grubhub"}
        assert order(p["grubhub"]) <= order(p["doordash"]) and order(p["ubereats"]) == order(p["doordash"])
        assert order(p["doordash"]) <= order(x["projected_runout"])
    egg = r["ajitama_egg"]  # habit: last 4 Thursdays x 1.10, rounded up to the batch
    u = IT.usage_by_day(st, [B.ddate(pd.Timestamp(D) - pd.Timedelta(days=7 * k)) for k in range(1, 5)])
    u = u[u.sku == "ajitama_egg"]
    assert egg["prep_source"] == "habit" and egg["prep"] == np.ceil(u.used.mean() * 1.1 / 30) * 30


def test_pause_times_grubhub_first_with_a_tight_supply():
    curve = [{"bin": 72 + i, "time": B.hm((72 + i) * 15), "orders": 20.0} for i in range(16)]
    p = plan.pause_times(curve, have=175, portions_per_order=1.0, buffer_portions=8)  # 15 left after 20:00
    assert p["grubhub"] < p["doordash"] == p["ubereats"]


def test_tomorrows_cards_cover_all_items_and_chashu_matches_plan():
    rows = H.days(now=datetime(2026, 11, 5, 23, 30), n=1)
    assert len(rows) == 1 and rows[0]["date"] == "2026-11-06" and rows[0]["weather_known"]
    t = rows[0]
    assert t["p10"] <= t["p50"] <= t["p90"] and t["rush"]["start"] < t["rush"]["end"]
    cards = t["cards"]
    assert [c["key"] for c in cards] == IT.KEYS and cards[0]["item"] == "Chashu"
    for c in cards:
        assert {"item", "target", "prep", "on_hand", "pause_at", "pause_if_busy", "recount_at", "unit"} <= set(c)
        assert c["prep"] % c["batch"] == 0 and c["prep"] >= 0
    with pytest.raises(ValueError):
        H.days(start=D, now=datetime(2026, 11, 5, 23, 30))  # never a past date
    # the close pipeline's chashu card is unchanged; extra_cards adds the other three after it
    from gondola.tools import demand
    st = B.store_at("2026-11-06", 0)
    fc = demand.run_forecast(st, "2026-11-06", B.day_errors("2026-11-06"))
    assert t["p50"] == fc["p50"]  # same day model as the nightly forecast
    extra = IT.extra_cards(st, fc)
    assert [c["key"] for c in extra] == ["ajitama_egg", "gyoza", "tonkotsu_broth"]
    ppo = float(np.mean(plan.chashu_portions_per_order(st, [s["date"] for s in fc["similar_days"]])))
    nv = plan.newsvendor_par(fc["p10"], fc["p50"], fc["p90"], ppo)
    assert IT.close_cards(st, fc)[0]["target"] == nv["chashu_portions"]


# ---------------------------------------------------------------- API
@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("GONDOLA_NOW", "2026-11-05T19:30:00")
    monkeypatch.setenv("GONDOLA_CLOCK", "frozen")
    from fastapi.testclient import TestClient
    from gondola.api.app import app
    with TestClient(app) as c:
        yield c


def test_api_future_contract(client):
    t = client.get("/api/future/today").json()
    assert t["date"] == D and t["now"] == "19:30"
    assert {"so_far", "expected", "rest", "bins", "drivers", "adjustments"} <= set(t)
    assert {"orders", "expected_by_now", "vs_expected_pct"} <= set(t["so_far"])
    assert all({"time", "channel"} <= set(b) for b in t["bins"])
    assert all("actual" not in b for b in t["bins"] if b["time"] > "19:30")  # nothing after now
    assert client.get("/api/future/today?date=2026-11-06").status_code == 400
    a = client.get("/api/future/arrivals").json()
    assert a and set(a[0]) == KEYS and a[0]["time"] == "19:30"
    it = client.get("/api/future/items").json()
    assert [x["key"] for x in it["items"]] == IT.KEYS
    assert all({"key", "name", "unit", "believed_left", "projected_runout", "pause_at", "recount_at"} <= set(x) for x in it["items"])
    d = client.get("/api/future/days").json()
    assert len(d) == 1 and d[0]["date"] == "2026-11-06" and len(d[0]["cards"]) == 4
    assert {"date", "p10", "p50", "p90", "rush", "drivers", "weather_known", "cards"} <= set(d[0])
    assert client.get("/api/future/days?start=2026-11-05").status_code == 400  # past
    assert client.get("/api/future/days?start=2026-11-07").status_code == 400  # horizon not enabled
    assert client.get("/api/future/days?n=7").status_code == 400
    early = client.get(f"/api/future/today?at=12:00").json()
    assert early["now"] == "12:00" and early["so_far"]["orders"] < t["so_far"]["orders"]
    assert client.get("/api/future/today?at=21:00").json()["now"] == "19:30"  # never past now
