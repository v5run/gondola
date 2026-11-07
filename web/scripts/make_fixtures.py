"""Build web/src/api/fixtures.json from the real demo data so the UI's mock mode shows true numbers.
Run from the repo root: python web/scripts/make_fixtures.py"""
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gondola.metrics import Store
from gondola.tools import analyst
from gondola.agents.ask import ask

st = Store()
D = "2026-11-05"
close = json.loads((ROOT / "out" / f"close_{D}.json").read_text())
daily = st.daily_frame()

def slot_curve(dates):
    q = """SELECT business_date, time_bucket(INTERVAL 15 MINUTE, created_at) AS bin, COUNT(*) n FROM orders
           WHERE business_date IN (SELECT unnest(?::DATE[])) GROUP BY 1,2"""
    x = st.df(q, [dates]); x["slot"] = x.bin.dt.hour * 4 + x.bin.dt.minute // 15
    s = x.groupby("slot").n.sum() / len(dates)
    return [{"time": f"{k//4:02d}:{k%4*15:02d}", "orders": round(float(s.get(k, 0)), 2)} for k in range(44, 92)]

cmp_ = close["analyst"]["compare"]
ov = {
    "date": D,
    "kpis": {"net_sales": close["books"]["money"]["net_sales"], "orders": close["books"]["money"]["orders"],
             "avg_ticket": close["books"]["money"]["avg_ticket"], "labour_pct": close["books"]["money"]["labour_pct"],
             "cancels": int(cmp_["cancels"]["value"]), "avoidable_cancels": int(cmp_["avoidable_cancels"]["value"])},
    "vs_usual": {k: cmp_[k]["change_pct"] for k in ("net_sales", "orders", "avg_ticket", "labour_pct")},
    "context": {"rain": close["analyst"]["explain"]["context"]["rain"], "events": close["analyst"]["explain"]["context"]["events"]},
    "curve_today": slot_curve([D]), "curve_usual": slot_curve(cmp_["baseline_dates"]),
    "channels": close["analyst"]["explain"]["channel"],
    "last_close": {"status": close["status"], "finished_at": close["as_of"]},
}
m = daily[daily.orders > 0]
metrics = [{"date": str(r.business_date.date()), "orders": int(r.orders), "net_sales": round(float(r.net_sales), 2),
            "avg_ticket": round(float(r.avg_ticket), 2), "labour_pct": round(float(r.labour_pct), 4), "cancels": int(r.cancels),
            "avoidable_cancels": int(r.avoidable_cancels), "rain": bool(r.rain), "events": r.events if isinstance(r.events, str) else ""}
           for r in m.itertuples()]
fc = close["demand"]
forecast = {k: fc[k] for k in ("date", "p10", "p50", "p90", "rush", "model")}
forecast["curve"] = [{"time": c["time"], "orders": c["orders"]} for c in fc["curve"]]
forecast["similar_days"] = [{"date": s["date"], "orders": s["orders"], "why": s["why"]} for s in fc["similar_days"]]
disputes = []
for v in close["books"]["verified"]:
    for f in v["findings"]:
        if f["kind"] == "error_charge_disputable":
            left = 14 - (pd.Timestamp(D) - pd.Timestamp(v["date"])).days
            if left > 0:
                disputes.append({"channel": {"doordash": "DoorDash", "ubereats": "Uber Eats", "grubhub": "Grubhub"}[f["channel"]],
                                 "order": f["evidence"][0], "amount": f["impact_usd"], "reason": f["detail"]["reason"],
                                 "items": f["detail"]["items"], "days_left": left, "date": v["date"]})
disputes.sort(key=lambda d: (d["days_left"], -d["amount"]))
close_detail = {"date": D, "status": close["status"], "seconds": close["seconds"], "log": close["log"],
                "findings": close["findings"], "alerts": close["alerts"], "card": close["plan"]["card"],
                "books": {"cash": close["books"]["cash"], "verified": [{"date": v["date"], "channels": v["channels"]} for v in close["books"]["verified"]],
                          "estimate_today": close["books"]["estimate_today"]},
                "disputes": disputes, "demand": {k: fc[k] for k in ("p10", "p50", "p90", "rush")}, "approved": False,
                "sold_out": close.get("sold_out")}
outbox = [json.loads(l) for l in (ROOT / "out" / "outbox.jsonl").read_text().splitlines()]
for o in outbox:
    o.pop("key", None)
    if isinstance(o.get("to"), list): o["to"] = ", ".join(o["to"])
    if o.get("attachment"): o["attachment"] = Path(o["attachment"]).name
outbox = list({(o["channel"], o["body"]): o for o in outbox}.values())[::-1]

# guard replay of demo night: minute ticks from 17:00 with the day's prep as stock
par = float(st.df("SELECT par FROM prep_log WHERE business_date = ?", [D]).par[0])
q = """SELECT o.created_at, o.channel, o.status, o.cancel_reason, SUM(m.chashu_portions) need FROM orders o
       JOIN order_lines l USING(order_id) JOIN menu m ON m.item=l.item WHERE o.business_date = ? GROUP BY ALL ORDER BY 1"""
ev = st.df(q, [D])
ev["minute"] = ev.created_at.dt.hour * 60 + ev.created_at.dt.minute
guard_orders = [{"m": int(r.minute), "ch": r.channel, "need": float(r.need),
                 "cancel": bool(r.status == "cancelled" and r.cancel_reason == "item_unavailable")}
                for r in ev.itertuples() if r.need > 0]
asks = {}
for q_ in ["How did we do tonight vs a usual Thursday?", "Why did we run out of chashu tonight?", "DoorDash sales last week?",
           "Which past days were most like tomorrow?", "How good has the forecast been lately?", "What's the forecast for tomorrow?",
           "uber vs doordash last month", "What was our best day this year?", "sales"]:
    a = ask(st, q_, D)
    asks[q_.lower()] = {"text": a.text, "clarify": a.clarify, "calls": [list(map(str, c)) for c in a.calls]}
fx = {"store": {"id": "hanabi-sqh", "name": "Hanabi Ramen", "address": "Murray Ave, Squirrel Hill, Pittsburgh", "today": D,
                "tomorrow": "2026-11-06", "first_date": metrics[0]["date"], "limited_items": ["Chashu"]},
      "overview": ov, "metrics": metrics, "forecast": forecast, "close": close_detail, "outbox": outbox,
      "guard": {"date": D, "par": par, "orders": guard_orders,
                "status_quo_cancels": int(sum(o["cancel"] for o in guard_orders))},
      "ask": asks}
out = ROOT / "web" / "src" / "api" / "fixtures.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(fx, default=str))
print(out, out.stat().st_size)
