"""Ask Agent: answers questions about the last 365 days through typed tools only (no raw SQL).

Two modes share the same tools:
  - LLM mode (Google ADK, see agents/adk_graph.py): the model chooses tools and writes the answer.
  - Offline mode (this file): an intent router picks the tool. Used for tests and when no API key is set.
Rule: if the date, metric or intent can't be resolved, ask a clarifying question. Never fall back to a default
and answer confidently.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

import pandas as pd

from .. import NP, clock  # noqa: F401  (clock re-exported)
from ..metrics import DEFS, Store
from ..tools import analyst, demand, stock

SELLOUT = re.compile(r"\b(run|ran|running|sell|sold|selling) ?(out|-out)\b|\bsellout\b|\b86(ed|'d)?\b")
APP_NAME = {"doordash": "DoorDash", "ubereats": "Uber Eats", "grubhub": "Grubhub"}


def _close_record(date: str) -> dict | None:
    import json
    from .. import pipeline
    f = pipeline.OUT / f"close_{date}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except Exception:  # noqa: BLE001
        return None


def _sellout_answer(store: Store, d: pd.Timestamp, label: str) -> "Answer":
    ds = str(d.date())
    so = stock.sold_out_summary(store, ds)
    calls = [("sold_out_summary", ds)]
    if not so:
        prep = stock.chashu_today(store, ds)
        txt = f"Chashu didn't sell out {label}" + (f": {prep['used']:.0f} of {prep['par']} portions were used." if prep else ".")
        return Answer(txt, calls, {"sold_out": None, "prep": prep})
    apps = ", ".join(f"{APP_NAME.get(k, k)} {v}" for k, v in so["by_channel"].items())
    txt = (f"Chashu sold out at {so['at'].lower()} {label}: you prepped {so['prepped']} portions and used {so['used']:.0f}. "
           f"It stayed live on the apps for {so['minutes_live']} more minutes, so {so['app_cancels']} app orders were cancelled "
           f"({apps}), about {so['portions_missed']:.1f} portions of demand we couldn't serve.")
    rec = _close_record(ds)
    card = ((rec or {}).get("plan") or {}).get("card") or []
    if card:
        c = card[0]
        pa, pb = c.get("pause_at") or {}, c.get("pause_if_busy") or {}
        when = pa if any(pa.values()) else pb
        pauses = ", ".join(f"{APP_NAME[k]} at {clock(v)}" for k, v in sorted(when.items(), key=lambda kv: kv[1] or "") if v)
        txt += (f" Tomorrow's card: make {c['prep']} chashu ({c['on_hand']:.0f} on hand)"
                + (f"; {'pause it' if any(pa.values()) else 'if it gets busy, pause it'} on {pauses}, keeping it for dine-in" if pauses else "")
                + (f"; recount when about {c['recount_at']} portions are left" if c.get("recount_at") else "") + ".")
        calls.append(("close_card", ds))
    elif rec is None:
        txt += " Tap Close shift to get tomorrow's prep card."
    return Answer(txt, calls, {"sold_out": so, "card": card})

METRIC_WORDS = [  # checked in order: specific before general
    ("avoidable_cancellations", ["avoidable", "store-caused", "sold-out cancel", "item unavailable"]),
    ("cancellations", ["cancel"]),
    ("error_charges", ["error charge", "error"]),
    ("commission", ["commission", "app fees", "delivery fees"]),
    ("card_fees", ["card fee", "processing fee"]),
    ("labour_pct", ["labour %", "labor %", "labour percent", "labor percent", "labour percentage", "labor percentage"]),
    ("labour_cost", ["labour cost", "labor cost", "payroll", "wages"]),
    ("labour_hours", ["labour hours", "labor hours", "hours worked"]),
    ("avg_ticket", ["average ticket", "avg ticket", "ticket size", "check size", "average order"]),
    ("tips", ["tip"]),
    ("orders", ["orders", "order count", "how many orders", "how busy", "covers"]),
    ("net_sales", ["sales", "revenue", "made", "make", "earn", "how'd we do", "how did we do"]),
]
CHANNELS = {"doordash": ["doordash", "door dash", "dd"], "ubereats": ["uber eats", "ubereats", "uber"],
            "grubhub": ["grubhub", "grub hub"], "in_store": ["in-store", "in store", "dine-in", "dine in", "walk-in"]}
NICE = {"doordash": "DoorDash", "ubereats": "Uber Eats", "grubhub": "Grubhub", "in_store": "in-store"}
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
DOWS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
HOLIDAYS = {"christmas eve": (12, 24), "christmas": (12, 25), "thanksgiving": None, "new year's eve": (12, 31),
            "new year's day": (1, 1), "valentine": (2, 14), "july 4": (7, 4), "fourth of july": (7, 4),
            "independence day": (7, 4), "labor day": None, "memorial day": None, "halloween": (10, 31)}
VOCAB = ["sales", "orders", "yesterday", "today", "doordash", "uber", "grubhub", "revenue", "cancellations", "forecast",
         "tomorrow", "average", "ticket", "labour", "labor", "commission", "week", "month", "compare"] + MONTHS + DOWS


@dataclass
class Answer:
    text: str
    calls: list = field(default_factory=list)
    data: dict | list | None = None
    clarify: bool = False


class Unclear(Exception):
    pass


def _fix_typos(q: str) -> str:
    out = []
    for w in re.findall(r"[\w'%/-]+|\S", q.lower()):
        if len(w) > 4 and w.isalpha() and w not in VOCAB:
            m = difflib.get_close_matches(w, VOCAB, n=1, cutoff=0.8)
            out.append(m[0] if m else w)
        else:
            out.append(w)
    return " ".join(out)


def _month_year(idx: int, year: int | None, today: pd.Timestamp) -> int:
    if year:
        return year
    return today.year if idx <= today.month else today.year - 1


def _day(y, m, d) -> pd.Timestamp:
    try:
        return pd.Timestamp(year=y, month=m, day=d)
    except ValueError:
        raise Unclear(f"{MONTHS[m - 1].title()} doesn't have a day {d}. Which date did you mean?")


def _dates(ql: str, today: pd.Timestamp, cal: pd.DataFrame):
    """(start, end, label), or None if the question has no date words."""
    ym = re.search(r"\b(20\d\d)\b", ql)
    year = int(ym.group(1)) if ym else None
    if "yesterday" in ql:
        d = today - pd.Timedelta(days=1); return d, d, "yesterday"
    if re.search(r"\b(today|tonight)\b", ql):
        return today, today, "today"
    if "this time last year" in ql or "same day last year" in ql:
        d = today - pd.DateOffset(years=1); return d, d, d.strftime(f"%b %{NP}d, %Y")
    m = re.search(r"\b(?:last|past) (\d+|two|three|four) (day|week)s?\b", ql)
    if m:
        n = {"two": 2, "three": 3, "four": 4}.get(m.group(1)) or int(m.group(1))
        days = n * (7 if m.group(2) == "week" else 1)
        return today - pd.Timedelta(days=days - 1), today, f"the last {days} days"
    if "last week" in ql:
        e = today - pd.Timedelta(days=today.dayofweek + 1); return e - pd.Timedelta(days=6), e, "last week"
    if "this week" in ql:
        return today - pd.Timedelta(days=today.dayofweek), today, "this week"
    if "last month" in ql:
        first = today.replace(day=1); e = first - pd.Timedelta(days=1); return e.replace(day=1), e, "last month"
    if "this month" in ql:
        return today.replace(day=1), today, "this month"
    if re.search(r"\b(this year|past year|last 365|last year)\b", ql):
        return today - pd.Timedelta(days=364), today, "the last 365 days"
    m = re.search(r"\b(20\d\d)-(\d\d)-(\d\d)\b", ql)
    if m:
        d = _day(int(m.group(1)), int(m.group(2)), int(m.group(3))); return d, d, d.strftime(f"%b %{NP}d, %Y")
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", ql)
    if m:
        mo, dy = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else _month_year(mo, None, today)
        y = y + 2000 if y < 100 else y
        d = _day(y, mo, dy); return d, d, d.strftime(f"%b %{NP}d, %Y")
    for h, md in HOLIDAYS.items():
        if h in ql:
            if md:
                y = year or (today.year if (md[0], md[1]) <= (today.month, today.day) else today.year - 1)
                d = _day(y, md[0], md[1])
            else:
                hit = cal[cal.holiday.fillna("").str.lower().str.startswith(h)]
                if hit.empty:
                    raise Unclear(f"I don't have {h.title()} in the calendar for the last year.")
                d = pd.Timestamp(hit.date.iloc[-1])
            return d, d, d.strftime(f"%b %{NP}d, %Y")
    for i, name in enumerate(MONTHS):
        m = re.search(rf"\b{name[:3]}[a-z]*\.? (\d{{1,2}})(?:st|nd|rd|th)?\b(?:,? (20\d\d))?", ql)
        if m:
            y = int(m.group(2)) if m.group(2) else _month_year(i + 1, year, today)
            d = _day(y, i + 1, int(m.group(1))); return d, d, d.strftime(f"%b %{NP}d, %Y")
    for i, name in enumerate(MONTHS):
        if re.search(rf"\b{name}\b", ql) and not (name == "may" and re.search(r"\bmay (we|i|you|have)\b", ql)):
            y = _month_year(i + 1, year, today)
            s = pd.Timestamp(year=y, month=i + 1, day=1); e = s + pd.offsets.MonthEnd(0)
            return s, min(e, today), s.strftime("%B %Y")
    m = re.search(r"\bthe (\d{1,2})(?:st|nd|rd|th)\b", ql)
    if m:
        dy = int(m.group(1))
        base = today if dy <= today.day else (today.replace(day=1) - pd.Timedelta(days=1))
        d = _day(base.year, base.month, dy); return d, d, d.strftime(f"%b %{NP}d, %Y")
    for i, name in enumerate(DOWS):
        if re.search(rf"\b{name}\b", ql):
            back = (today.dayofweek - i) % 7 or 7
            d = today - pd.Timedelta(days=back); return d, d, f"{name.title()} {d:%b %{NP}d}"
    return None


def _metric(ql: str) -> str | None:
    for m, words in METRIC_WORDS:
        if any(re.search(rf"(?<![\w]){re.escape(w)}", ql) for w in words):
            return m
    return None


def _channels(ql: str) -> list[str]:
    return [ch for ch, words in CHANNELS.items() if any(re.search(rf"\b{re.escape(w)}\b", ql) for w in words)]


def _fmt(metric: str, v: float) -> str:
    if metric in ("net_sales", "labour_cost", "error_charges", "commission", "app_sales", "avg_ticket", "card_fees", "tips"):
        return f"${v:,.2f}"
    if metric == "labour_pct":
        return f"{v:.1%}"
    if metric == "labour_hours":
        return f"{v:,.1f} hours"
    return f"{v:,.0f}"


def _value(store: Store, m: str, s, e, ch):
    s, e = str(s.date()), str(e.date())
    if m == "labour_pct":
        ns = store.metric_total("net_sales", s, e)
        return store.metric_total("labour_cost", s, e) / ns if ns else 0.0
    if m in ("labour_cost", "labour_hours"):
        return store.metric_total(m, s, e)
    if m == "card_fees":
        o = store.df("SELECT subtotal, tax, tip FROM orders WHERE channel='in_store' AND tender='card' AND status='completed' "
                     "AND business_date BETWEEN ? AND ?", [s, e])
        return float((o.subtotal + o.tax + o.tip).sum() * 0.029 + 0.30 * len(o))
    if m == "tips":
        return float(store.df("SELECT COALESCE(SUM(tip),0) t FROM orders WHERE status='completed' AND business_date BETWEEN ? AND ?",
                              [s, e]).t[0])
    return store.metric_total(m, s, e, ch)


def ask(store: Store, question: str, today: str | None = None) -> Answer:
    try:
        return _ask(store, question, today)
    except Unclear as u:
        return Answer(str(u), [], None, clarify=True)
    except (ValueError, KeyError, IndexError) as e:
        return Answer(f"I couldn't work that out. Could you rephrase with a date, like 'sales on Oct 3'?", [], {"error": "Unable to interpret question"}, clarify=True)


def _ask(store: Store, question: str, today: str | None) -> Answer:
    t = pd.Timestamp(today) if today else store.last_date()
    first = pd.Timestamp(store.df("SELECT min(business_date) d FROM orders").d[0])
    ql = _fix_typos(question.strip())
    menu_words = [w for it in store.df("SELECT item FROM menu").item for w in [it.lower(), it.lower().split()[0]] if len(w) > 4]
    known = _metric(ql) or _channels(ql) or any(w in ql for w in menu_words) or re.search(r"\b(why|forecast|tomorrow|rush|similar|best|worst|busiest|slowest|item|seller|compare|explain|happened|sold)\b", ql)
    if not ql or not known:
        raise Unclear("What would you like to know? For example: 'sales yesterday', 'DoorDash orders last week' or 'why was Friday busy?'")
    cal = store.df("SELECT date, holiday FROM calendar")
    dr = _dates(ql, t, cal)

    if re.search(r"\b(tomorrow|tmrw)\b", ql) and not re.search(r"(accura|error|how good|how close|similar|like tomorrow|days like)", ql) \
            or re.search(r"\b(what'?s|whats) the forecast\b|\bforecast for\b", ql):
        target = str((t + pd.Timedelta(days=1)).date())
        fc = demand.run_forecast(store, target)
        return Answer(f"Tomorrow ({pd.Timestamp(target):%a %b %{NP}d}): about {fc['p50']:.0f} orders (likely {fc['p10']:.0f}–{fc['p90']:.0f}), "
                      f"rush {fc['rush']['start']}–{fc['rush']['end']}.", [("run_forecast", target)], fc)
    if "similar" in ql or "days like" in ql or "like tomorrow" in ql:
        target = str((t + pd.Timedelta(days=1)).date()) if "tomorrow" in ql else str((dr[0] if dr else t).date())
        sims = analyst.find_similar_days(store, target, 5)
        return Answer("Most similar past days: " + "; ".join(f"{pd.Timestamp(x['date']):%a %b %{NP}d} ({x['orders']} orders, "
                      f"{x['why'] or 'closest overall'})" for x in sims), [("find_similar_days", target)], sims)
    if "forecast" in ql:
        if dr and dr[0] == dr[1] and dr[2] != "today":
            r = demand.backtest_forecast(store, str(dr[0].date()))
            if r is None:
                raise Unclear("There isn't enough history before that day to re-run a forecast.")
            return Answer(f"For {dr[2]}, the forecast made with data up to the night before was {r['predicted']:.0f} orders; actual was "
                          f"{r['actual']:.0f} ({r['error_pct']:+.1%}). Same weekday last month would have said {r['naive_same_weekday']:.0f}.",
                          [("backtest_forecast", str(dr[0].date()))], r)
        bt = demand.rolling_backtest(store, days=30, end=str(t.date()))
        return Answer(f"Over the last 30 days the forecast was off by {bt.error_pct.abs().mean():.1%} on average, against "
                      f"{bt.naive_error_pct.abs().mean():.1%} for same-weekday averages.", [("backtest_forecast", "last 30 days")],
                      bt.to_dict("records"))
    if re.search(r"\brush\b", ql):
        target = str((t + pd.Timedelta(days=1)).date())
        fc = demand.run_forecast(store, target)
        return Answer(f"Tomorrow's rush: {fc['rush']['start']}–{fc['rush']['end']}, peaking near {fc['rush']['peak_per_15min']:.0f} "
                      f"orders per 15 minutes.", [("run_forecast", target)], fc["rush"])

    if SELLOUT.search(ql):
        d = dr[0] if dr and dr[0] == dr[1] else t
        return _sellout_answer(store, d, "tonight" if d == t else f"{d:%a %b %{NP}d}")

    if dr is None:
        if re.search(r"(how'd we do|how did we do)", ql) or ql.startswith("why") or "what happened" in ql:
            dr = (t, t, "today")  # a question on the close night is about tonight
        else:
            raise Unclear("Which day or period? For example 'yesterday', 'last week' or 'Oct 3'.")
    s, e, label = dr
    if e < first or s > t:
        raise Unclear(f"I only have data from {first:%b %{NP}d, %Y} to {t:%b %{NP}d, %Y}.")
    if s < first:
        s, label = first, f"{label} (data starts {first:%b %{NP}d, %Y})"

    if ql.startswith("why") or "what happened" in ql or "explain" in ql:
        x = analyst.explain_change(store, str(s.date()))
        if x.get("status") == "no_data":
            ev = ", ".join(e_ for e_ in x["context"]["events"] if e_) or "no orders recorded"
            return Answer(f"{label}: the store was closed ({ev}).", [("explain_change", str(s.date()))], x)
        c = analyst.compare_periods(store, str(s.date()))
        if c["net_sales"]["change_pct"] is None:
            raise Unclear(f"There's no usual {s.day_name()} to compare {label} with yet.")
        chs = [r for r in x["channel"] if r["key"] in NICE]
        ch = max(chs, key=lambda r: abs(r["change"]))
        dp = max(x["daypart"], key=lambda r: abs(r["change"]))
        ctx = x["context"]
        why = [w for w in ["rain" if ctx["rain"] else None, "snow" if ctx["snow"] else None] + ctx["events"] if w]
        sim = analyst.compare_periods(store, str(s.date()), baseline="similar_days")
        base_ev = store.df("SELECT DISTINCT date FROM events WHERE event NOT LIKE 'Pirates%' AND date IN (SELECT unnest(?::DATE[]))", [c["baseline_dates"]])
        base_rain = store.df("SELECT COUNT(*) n FROM calendar WHERE rain AND date IN (SELECT unnest(?::DATE[]))", [c["baseline_dates"]]).n[0]
        caveat = ""
        if (len(base_ev) or base_rain) and sim["net_sales"]["change_pct"] is not None:
            caveat = (f" The usual-{s.day_name()} average includes {len(base_ev)} game night{'s' if len(base_ev) != 1 else ''} and "
                      f"{base_rain} rainy day{'s' if base_rain != 1 else ''}; against the most similar past days it was "
                      f"{sim['net_sales']['change_pct']:+.0%}.")
        txt = (f"{label[0].upper() + label[1:]}: net sales ${c['net_sales']['value']:,.0f} vs ${c['net_sales']['baseline']:,.0f} on a usual "
               f"{s.day_name()} ({c['net_sales']['change_pct']:+.0%}). Biggest move: {NICE[ch['key']]} ({ch['change']:+,.0f}), "
               f"mostly at {dp['key']} ({dp['change']:+,.0f}). Context: {', '.join(why) if why else 'nothing unusual'}.{caveat}")
        return Answer(txt, [("explain_change", str(s.date())), ("compare_periods", str(s.date()))], {"explain": x, "compare": c})

    m = _metric(ql)
    chans = _channels(ql)
    if len(chans) >= 2:
        m = m or "net_sales"
        vals = {ch: _value(store, m, s, e, ch) for ch in chans}
        name = DEFS[m]["label"] if m in DEFS else m
        return Answer(f"{name} for {label}: " + ", ".join(f"{NICE[c]} {_fmt(m, v)}" for c, v in vals.items()) + ".",
                      [("query_metric", m, label, c) for c in chans], vals)
    menu = store.df("SELECT item FROM menu").item.tolist()
    named = [it for it in menu if it.lower() in ql or (len(it.split()[0]) > 4 and it.lower().split()[0] in ql.split())]
    if named and m in (None, "orders"):
        df = store.query_metric("orders", str(s.date()), str(e.date()), "item")
        df = df[df.key.isin(named)]
        return Answer(f"Sold for {label}: " + (", ".join(f"{r.key} {r.value:,.0f}" for r in df.itertuples()) or "none") + ".",
                      [("query_metric", "orders", "item", label)], df.to_dict("records"))
    if re.search(r"\b(item|items|seller|dish|sold the most|popular)\b", ql):
        df = store.query_metric("orders", str(s.date()), str(e.date()), "item")
        top = df.nlargest(3, "value")
        return Answer(f"Top items for {label}: " + ", ".join(f"{r.key} ({r.value:,.0f})" for r in top.itertuples()) + ".",
                      [("query_metric", "orders", "item", label)], top.to_dict("records"))
    if re.search(r"\b(best|worst|busiest|slowest)\b", ql):
        m2 = m if m in ("net_sales", "orders") else "net_sales"
        if s == e:
            s, label = t - pd.Timedelta(days=364), "the last 365 days"
        df = store.query_metric(m2, str(s.date()), str(e.date()), "day")
        df = df[df.value > 0]
        top = re.search(r"\b(best|busiest)\b", ql) is not None
        r = df.nlargest(1, "value") if top else df.nsmallest(1, "value")
        k = pd.Timestamp(r.key.iloc[0])
        return Answer(f"{'Best' if top else 'Slowest'} day in {label}: {k:%a %b %{NP}d} with {_fmt(m2, r.value.iloc[0])}.",
                      [("query_metric", m2, label)], r.to_dict("records"))
    if re.search(r"\b(compare|compared|vs|versus)\b", ql):
        c = analyst.compare_periods(store, str(s.date()))
        mm = m if (m in c and isinstance(c.get(m), dict)) else "net_sales"
        r = c[mm]
        if r["change_pct"] is None:
            raise Unclear(f"There's no usual {s.day_name()} to compare {label} with yet.")
        return Answer(f"{label[0].upper() + label[1:]}: {_fmt(mm, r['value'])} vs {_fmt(mm, r['baseline'])} on a usual {s.day_name()} "
                      f"({r['change_pct']:+.1%}).", [("compare_periods", str(s.date()))], c)
    if m is None:
        if chans:
            m = "net_sales"
        else:
            raise Unclear("Which number: sales, orders, average ticket, labour, cancellations or app fees?")
    no_channel = m in ("labour_cost", "labour_hours", "labour_pct", "card_fees", "tips")
    ch = chans[0] if chans and not no_channel else None
    v = _value(store, m, s, e, ch)
    lab = DEFS[m]["label"] if m in DEFS else {"labour_pct": "Labour %", "card_fees": "Card fees (in-store)", "tips": "Tips"}[m]
    note = " (labour isn't split by channel)" if chans and no_channel and m.startswith("labour") else ""
    where = f" on {NICE[ch]}" if ch else ""
    return Answer(f"{lab}{where} for {label}: {_fmt(m, v)}{note}.", [("query_metric", m, label, ch)],
                  {"metric": m, "start": str(s.date()), "end": str(e.date()), "channel": ch, "value": v})
