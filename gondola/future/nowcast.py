"""Nowcast: the rest of today, per channel and per 15 minutes, corrected by the orders seen so far.

1. Start from the morning forecast (the night-before LightGBM daily total, spread over the similar days' 15-minute
   curve and split by channel; see base.morning).
2. Compare actual completed orders so far with what that forecast expected by now:
       raw = actual / expected            (cumulative since opening, clipped to 0.5..2)
       w   = min(expected / (expected + K), 0.5)   (shrinkage weight: grows as the day's evidence grows, capped)
       r   = 1 + w * (raw - 1)            (applied to everything still to come)
   Because the ratio is cumulative and shrunk, one slow half-hour moves the evening only a little; a whole slow
   afternoon moves it a lot. A second, more strongly shrunk ratio (K_CHANNEL) tilts the channel mix, then the
   channels are rescaled so the total still follows r.
3. Ranges come from backtested errors: for the 60 open days before the date, the same nowcast is re-run at several
   cut times and its rest-of-day error is recorded. P10/P90 of the rest of the day = the 10th/90th percentile log
   error at the nearest cut times; per-bin ranges add count noise (overdispersion fitted on the same backtest).

K, K_CHANNEL and the 0.5 cap were picked on an earlier window (days 61-120 before 2026-11-05) and are reported on the
last 60 days by `backtest` (numbers in docs/development/FEATURE_COVERAGE.md). On the synthetic store the day so far
predicts the rest of the day only weakly in the latest 60 days (evening sell-outs cut completed orders), so the
nowcast helps at lunch, ties mid-afternoon and is slightly worse than the morning forecast at 19:00 there.
"""
from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd

from . import base as B
from .base import CHANNELS, DB, hm

K = 150.0           # orders of evidence needed before the ratio counts half (tuned on an earlier window)
K_CHANNEL = 150.0   # same for each channel's tilt (per-channel evidence is thinner)
W_MAX = 0.5         # cap on the shrinkage weight: the day so far never explains more than half the gap
CLIP = (0.5, 2.0)
Z = 1.2816          # normal 90th percentile
ERROR_CUTS = ["11:00"] + [f"{h:02d}:00" for h in range(12, 23)]  # cut times for the error table (before close only)
_TABLES = B.LRU(64)


# ------------------------------------------------------------------ the correction (pure)
def correction(base: pd.DataFrame, act: pd.DataFrame, m: int, k: float = K, k_channel: float = K_CHANNEL,
               w_max: float | None = None) -> dict:
    """base: (bin, channel, p50) for the whole day; act: (bin, channel, n) actual orders created before minute m.
    Returns the ratios and, per channel, the factor for the rest of the day."""
    cb, frac = m // 15, (m % 15) / 15
    w_past = np.where(base.bin < cb, 1.0, np.where(base.bin == cb, frac, 0.0))
    exp_ch = (base.p50 * w_past).groupby(base.channel).sum().reindex(CHANNELS, fill_value=0.0)
    rest_ch = (base.p50 * (1 - w_past)).groupby(base.channel).sum().reindex(CHANNELS, fill_value=0.0)
    a = act.groupby("channel").n.sum().reindex(CHANNELS, fill_value=0.0) if len(act) else pd.Series(0.0, index=CHANNELS)
    F, A = float(exp_ch.sum()), float(a.sum())
    raw = A / F if F > 0 else 1.0
    w = min(F / (F + k), W_MAX if w_max is None else w_max) if F > 0 else 0.0
    r = 1 + w * (float(np.clip(raw, *CLIP)) - 1)
    tilt = {}
    for c in CHANNELS:
        fc_ = float(exp_ch[c])
        if fc_ > 0 and raw > 0:
            rel = (float(a[c]) / fc_) / raw
            wc = fc_ / (fc_ + k_channel)
            tilt[c] = 1 + wc * (float(np.clip(rel, *CLIP)) - 1)
        else:
            tilt[c] = 1.0
    tilted = sum(float(rest_ch[c]) * tilt[c] for c in CHANNELS)
    scale = float(rest_ch.sum()) / tilted if tilted > 0 else 1.0
    factor = {c: r * tilt[c] * scale for c in CHANNELS}
    return {"expected_by_now": F, "actual": A, "raw_ratio": raw, "weight": w, "ratio": r, "factor": factor,
            "by_channel": {c: {"actual": float(a[c]), "expected": float(exp_ch[c])} for c in CHANNELS}}


def rest_bins(base: pd.DataFrame, m: int, factor: dict) -> pd.DataFrame:
    """Remaining (bin, channel, p50): the current bin keeps only its unexpired fraction."""
    cb, frac = m // 15, (m % 15) / 15
    x = base[base.bin >= cb].copy()
    x["p50"] = x.p50 * x.channel.map(factor) * np.where(x.bin == cb, 1 - frac, 1.0)
    return x


# ------------------------------------------------------------------ backtest rows (shared by the error table and the report)
def _day_rows(D: str, p50: float, cnt: pd.DataFrame, daily: pd.DataFrame, cuts: list[str], k: float, kc: float,
              db=DB) -> list[dict]:
    """Re-run the nowcast for a past day D at each cut, from its night-before total p50 (no data of D in the base)."""
    from ..tools.analyst import find_similar_days
    sims = [s["date"] for s in find_similar_days(None, D, 5, daily[daily.business_date <= pd.Timestamp(D)])]
    shape = B.channel_shape(D, sims, db, cnt)
    base = shape.assign(p50=shape.share * p50)
    day = cnt[cnt.business_date == pd.Timestamp(D)]
    close = B.close_bin(D) * 15
    rows = []
    for c in cuts:
        m = B.mins(c)
        if m >= close:
            continue
        act = day[day.bin * 15 < m]  # bins are whole: cuts fall on bin edges
        cor = correction(base, act, m, k, kc)
        rb = rest_bins(base, m, cor["factor"])
        later = day[day.bin * 15 >= m]
        a_rest = float(later.n.sum())
        b_rest = float(base[base.bin * 15 >= m].p50.sum())
        bins = rb.merge(later[["bin", "channel", "n"]], on=["bin", "channel"], how="left").fillna({"n": 0})
        rows.append({"date": D, "cut": c, "base_rest": b_rest, "now_rest": float(rb.p50.sum()), "actual_rest": a_rest,
                     "ratio": cor["ratio"], "raw": cor["raw_ratio"], "bins": bins[["bin", "channel", "p50", "n"]]})
    return rows


def _rows_for(dates: list[str], cuts: list[str], k: float, kc: float, db=DB) -> list[dict]:
    bt = B.day_backtests(dates, db).set_index("date")
    cnt, daily = B.counts(db), B.daily(db)
    out = []
    for D in dates:
        if D not in bt.index:
            continue
        out += _day_rows(D, float(bt.loc[D, "predicted"]), cnt, daily, cuts, k, kc, db)
    return out


def _table_from_rows(rows: list[dict]) -> dict:
    """{cut: {q10, q50, q90, n}} of log(actual_rest / nowcast_rest), plus bin overdispersion phi."""
    tab = {}
    df = pd.DataFrame([{k: r[k] for k in ("date", "cut", "now_rest", "actual_rest")} for r in rows])
    if df.empty:
        return {"cuts": {}, "phi": 1.5, "n_days": 0}
    df = df[(df.now_rest > 5) & (df.actual_rest > 0)]
    df["lerr"] = np.log(df.actual_rest / df.now_rest)
    for c, g in df.groupby("cut"):
        q10, q50, q90 = np.quantile(g["lerr"], [0.1, 0.5, 0.9])
        tab[c] = {"q10": float(q10), "q50": float(q50), "q90": float(q90), "n": int(len(g))}
    # overdispersion of bin counts beyond the level error: E[(a - mu)^2] = phi*mu + (sigma*mu)^2
    num, den = 0.0, 0.0
    for r in rows:
        t = tab.get(r["cut"])
        if not t:
            continue
        s = (t["q90"] - t["q10"]) / (2 * Z)
        b = r["bins"]
        mu = b.p50.values
        num += float(np.sum((b.n.values - mu) ** 2 - (s * mu) ** 2))
        den += float(np.sum(mu))
    phi = max(1.0, num / den) if den > 0 else 1.5
    return {"cuts": tab, "phi": round(phi, 3), "n_days": int(df.date.nunique())}


def error_table(date: str, db=DB) -> dict:
    """Backtested nowcast errors for the 60 open days before `date` (cached in memory and in out/future)."""
    date = B.ddate(date)

    def build():
        p = B.out_dir() / "nowcast_errors" / f"{date}_k{int(K)}_{int(K_CHANNEL)}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
        rows = _rows_for(B.open_days_before(date, B.ERROR_DAYS, db), ERROR_CUTS, K, K_CHANNEL, db)
        t = _table_from_rows(rows)
        t["n_days"] = len({r["date"] for r in rows})
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(t), encoding="utf-8")
        return t
    return _TABLES.get((str(db), B.db_version(db), date), build)


def level_quantiles(tab: dict, m: int, morning: dict) -> tuple[float, float]:
    """(q10, q90) log error of the rest of the day at minute m: interpolated between the table's cuts. Before the
    first cut (or with no table) the morning conformal range is used."""
    cuts = sorted(((B.mins(c), v) for c, v in (tab.get("cuts") or {}).items()), key=lambda x: x[0])
    if not cuts or m <= cuts[0][0]:
        if cuts and m >= B.OPEN_BIN * 15:
            return cuts[0][1]["q10"], cuts[0][1]["q90"]
        return float(np.log(morning["lo"])), float(np.log(morning["hi"]))
    for (m0, a), (m1, b) in zip(cuts, cuts[1:]):
        if m0 <= m <= m1:
            t = (m - m0) / (m1 - m0)
            return a["q10"] + t * (b["q10"] - a["q10"]), a["q90"] + t * (b["q90"] - a["q90"])
    return cuts[-1][1]["q10"], cuts[-1][1]["q90"]


# ------------------------------------------------------------------ the nowcast for one moment
def nowcast(date: str, now: datetime | None = None, db=DB, m: int | None = None) -> dict:
    """Everything about the rest of `date` at `now` (store clock if None). m overrides the cut minute (tests)."""
    date = B.ddate(date)
    m = B.cut_minute(date, now, db) if m is None else m
    mo = B.morning(date, db)
    base = mo["bins"]
    act = B.actual_bins(date, m, db)
    close = B.close_bin(date) * 15
    cor = correction(base, act, m)
    rb = rest_bins(base, m, cor["factor"]) if m < close else base.iloc[0:0].assign(p50=[])
    tab = error_table(date, db)
    q10, q90 = level_quantiles(tab, m, mo)
    s = (q90 - q10) / (2 * Z)
    phi = float(tab.get("phi") or 1.5)
    mu = rb.p50.values.astype(float)
    sd = np.sqrt(phi * mu + (s * mu) ** 2)
    rb = rb.assign(p10=np.maximum(0.0, mu - Z * sd), p90=mu + Z * sd)
    rest50 = float(rb.p50.sum())
    rest = {"p10": min(rest50, rest50 * float(np.exp(q10))), "p50": rest50, "p90": max(rest50, rest50 * float(np.exp(q90)))}
    return {"date": date, "minute": m, "morning": mo, "correction": cor, "rest_bins": rb, "rest": rest,
            "actual_bins": act, "error_table": {"cut_q10": q10, "cut_q90": q90, "phi": phi, "n_days": tab.get("n_days")},
            "closed": m >= close}


def arrivals(date: str, now: datetime | None = None, db=DB, issue: bool = True) -> list[dict]:
    """Future -> Present contract: [{time:"HH:MM", channel, p10, p50, p90}] for each remaining 15-minute bin of
    `date` (the current bin counts only its remaining minutes); empty once closed. Issues one forecast.issued
    ledger event per date and bin (idempotent)."""
    nc = nowcast(date, now, db)
    out = [{"time": hm(int(r.bin) * 15), "channel": r.channel, "p10": round(float(r.p10), 2), "p50": round(float(r.p50), 2),
            "p90": round(float(r.p90), 2)} for r in nc["rest_bins"].sort_values(["bin", "channel"]).itertuples()]
    if issue:
        issue_event(nc, out)
    return out


def issue_event(nc: dict, bins: list[dict]) -> None:
    """forecast.issued {horizon:"rest_of_day"} keyed by date + the 15-minute bin it was made in. Never raises."""
    if nc["closed"] or not bins:
        return
    try:
        from ..ledger import ledger
        d, b = nc["date"], hm(nc["minute"] // 15 * 15)
        r = nc["rest"]
        ledger().append("forecast.issued", d, f"{d}T{b}:00", {
            "horizon": "rest_of_day", "for_date": d, "bin": b,
            "total": {k: round(v, 1) for k, v in r.items()},
            "so_far": {"orders": nc["correction"]["actual"], "expected": round(nc["correction"]["expected_by_now"], 1)},
            "ratio": round(nc["correction"]["ratio"], 4), "bins": bins}, source="future", key=f"forecast.issued:rest_of_day:{d}:{b}")
    except Exception:  # noqa: BLE001 - the ledger must never break a forecast
        pass


def today_view(date: str, now: datetime | None = None, db=DB, issue: bool = False) -> dict:
    """The /api/future/today payload (without drivers/adjustments, which the API adds)."""
    nc = nowcast(date, now, db)
    if issue:
        issue_event(nc, [{"time": hm(int(r.bin) * 15), "channel": r.channel, "p10": round(float(r.p10), 2),
                          "p50": round(float(r.p50), 2), "p90": round(float(r.p90), 2)}
                         for r in nc["rest_bins"].sort_values(["bin", "channel"]).itertuples()])
    mo, cor, m = nc["morning"], nc["correction"], nc["minute"]
    act = nc["actual_bins"]
    A = cor["actual"]
    bins = []
    cb = m // 15
    base = mo["bins"]
    a_map = {(int(r.bin), r.channel): int(r.n) for r in act.itertuples()} if len(act) else {}
    rest = {(int(r.bin), r.channel): r for r in nc["rest_bins"].itertuples()}
    for r in base.sort_values(["bin", "channel"]).itertuples():
        key = (int(r.bin), r.channel)
        row = {"time": hm(int(r.bin) * 15), "channel": r.channel, "forecast_p50": round(float(r.p50), 2)}
        if key in rest:
            x = rest[key]
            row.update(p10=round(float(x.p10), 2), p50=round(float(x.p50), 2), p90=round(float(x.p90), 2))
        if int(r.bin) <= cb and m > 0:
            row["actual"] = a_map.get(key, 0)
        bins.append(row)
    rest_t = nc["rest"]
    F = cor["expected_by_now"]
    return {
        "date": nc["date"], "now": hm(min(m, 24 * 60 - 1)) if m < B.FULL_DAY else None, "closed": nc["closed"],
        "so_far": {"orders": int(A), "expected_by_now": round(F, 1),
                   "vs_expected_pct": round((A / F - 1) * 100, 1) if F > 0 else None,
                   "by_channel": {c: {"orders": int(v["actual"]), "expected_by_now": round(v["expected"], 1)}
                                  for c, v in cor["by_channel"].items()}},
        "expected": {k: round(A + v, 1) for k, v in rest_t.items()},
        "rest": {k: round(v, 1) for k, v in rest_t.items()},
        "morning": {k: mo[k] for k in ("p10", "p50", "p90")} | {"model": mo["model"], "adjustment_factor": mo["adjustment_factor"]},
        "nowcast": {"raw_ratio": round(cor["raw_ratio"], 4), "weight": round(cor["weight"], 4), "ratio": round(cor["ratio"], 4),
                    "k": K, "range_from_days": nc["error_table"]["n_days"]},
        "rush": mo["rush"], "similar_days": [{k: s[k] for k in ("date", "orders", "why")} for s in mo["similar_days"]],
        "bins": bins,
    }


# ------------------------------------------------------------------ backtest report
def backtest(end: str, days: int = 60, cuts: tuple = ("13:00", "17:00", "19:00"), k: float = K, k_channel: float = K_CHANNEL,
             db=DB, calib_days: int = B.ERROR_DAYS) -> dict:
    """Nowcast vs the morning-only forecast on the `days` open days up to `end` (inclusive), at each cut.
    Each day's base is its own night-before forecast (no data of that day); ranges for day D come from the
    `calib_days` days before D only."""
    all_dates = B.open_days_before(B.ddate(pd.Timestamp(end) + pd.Timedelta(days=1)), days + calib_days, db)
    test = all_dates[-days:]
    rows = _rows_for(all_dates, list(ERROR_CUTS), k, k_channel, db)
    by_date: dict = {}
    for r in rows:
        by_date.setdefault(r["date"], []).append(r)
    res = {}
    for c in cuts:
        recs = []
        for D in test:
            r = next((x for x in by_date.get(D, []) if x["cut"] == c), None)
            if r is None or r["actual_rest"] <= 0:
                continue
            i = all_dates.index(D)
            calib = [x for d_ in all_dates[max(0, i - calib_days):i] for x in by_date.get(d_, [])]
            tab = _table_from_rows(calib)
            t = tab["cuts"].get(c)
            lo, hi = (np.exp(t["q10"]), np.exp(t["q90"])) if t else (np.nan, np.nan)
            s = (t["q90"] - t["q10"]) / (2 * Z) if t else np.nan
            b = r["bins"]
            mu = b.p50.values
            sd = np.sqrt(tab["phi"] * mu + (s * mu) ** 2)
            inside = (b.n.values >= np.maximum(0, mu - Z * sd)) & (b.n.values <= mu + Z * sd)
            recs.append({"date": D, "actual": r["actual_rest"], "morning": r["base_rest"], "nowcast": r["now_rest"],
                         "covered": bool(r["now_rest"] * lo <= r["actual_rest"] <= r["now_rest"] * hi),
                         "bin_cov": float(inside.mean()) if len(inside) else np.nan})
        x = pd.DataFrame(recs)
        if x.empty:
            continue
        ae_m, ae_n = (x.morning - x.actual).abs(), (x.nowcast - x.actual).abs()
        res[c] = {"days": int(len(x)),
                  "morning_mae": round(float(ae_m.mean()), 1), "nowcast_mae": round(float(ae_n.mean()), 1),
                  "morning_mape": round(float((ae_m / x.actual).mean()), 4), "nowcast_mape": round(float((ae_n / x.actual).mean()), 4),
                  "morning_bias": round(float(((x.morning - x.actual) / x.actual).mean()), 4),
                  "nowcast_bias": round(float(((x.nowcast - x.actual) / x.actual).mean()), 4),
                  "nowcast_better_days": int((ae_n < ae_m).sum()),
                  "rest_p10_p90_coverage": round(float(x.covered.mean()), 3),
                  "bin_channel_p10_p90_coverage": round(float(x.bin_cov.mean()), 3)}
    return {"end": B.ddate(end), "days": len(test), "k": k, "k_channel": k_channel, "cuts": res}


if __name__ == "__main__":  # python -m gondola.future.nowcast [end_date]
    import sys
    print(json.dumps(backtest(sys.argv[1] if len(sys.argv) > 1 else "2026-11-05"), indent=1))
