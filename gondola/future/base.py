"""Shared plumbing for Future: the store clock cut, the morning (day) forecast split into channels and 15-minute
bins, backtested error tables, small caches and the Future output folder.

Units: "orders" are completed orders (the unit the daily model forecasts and the dashboards count). Times are
store-local; a bin is 15 minutes, numbered from midnight (44 = 11:00).

No data after "now": every Store opened here is cut (Store(cut=...)); the morning forecast for a day sees only the
days before it, and actuals for a day are cut at the minute asked for.
"""
from __future__ import annotations

import json
import math
import os
import threading
from collections import OrderedDict
from datetime import date as Date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .. import now as clock
from ..metrics import ROOT, Store
from ..tools import demand
from ..tools.analyst import find_similar_days

DB = ROOT / "data" / "gondola.duckdb"
CHANNELS = ["doordash", "ubereats", "grubhub", "in_store"]
APPS = ["doordash", "ubereats", "grubhub"]
CHANNEL_NAME = {"doordash": "DoorDash", "ubereats": "Uber Eats", "grubhub": "Grubhub", "in_store": "in-store"}
OPEN_BIN = clock.OPEN_MIN // 15
FULL_DAY = 28 * 60  # minutes after the day's midnight that cover the whole business day (it runs to 4 a.m.)
MIX_SMOOTH_BINS = 5  # channel mix per bin is smoothed over +-2 bins (5 similar days are thin per channel)
ERROR_DAYS = 60


# ------------------------------------------------------------------ small helpers
def hm(m: int) -> str:
    m = int(m)
    return f"{m // 60:02d}:{m % 60:02d}"


def mins(t: str) -> int:
    h, m = t.split(":")[:2]
    return int(h) * 60 + int(m)


def ddate(d) -> str:
    return str(pd.Timestamp(d).date())


def close_bin(date: str) -> int:
    return clock.close_min(date) // 15


def out_dir() -> Path:
    p = Path(os.getenv("GONDOLA_FUTURE_DIR") or (ROOT / "out" / "future"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_version(db) -> int:
    try:
        return Path(db).stat().st_mtime_ns
    except FileNotFoundError:
        return 0


class LRU:
    """Tiny thread-safe memo: get(key, fn) computes once per key (concurrent first calls compute once)."""

    def __init__(self, maxsize: int = 256):
        self.d: OrderedDict = OrderedDict()
        self.maxsize = maxsize
        self.lock = threading.Lock()
        self.inflight: dict = {}

    def get(self, key, fn):
        with self.lock:
            if key in self.d:
                self.d.move_to_end(key)
                return self.d[key]
            ev = self.inflight.get(key)
            owner = ev is None
            if owner:
                ev = self.inflight[key] = threading.Event()
        if not owner:
            ev.wait(120)
            with self.lock:
                if key in self.d:
                    return self.d[key]
        try:
            v = fn()
            with self.lock:
                self.d[key] = v
                while len(self.d) > self.maxsize:
                    self.d.popitem(last=False)
            return v
        finally:
            if owner:
                with self.lock:
                    self.inflight.pop(key, None)
                ev.set()

    def clear(self):
        with self.lock:
            self.d.clear()


CACHE = LRU(512)


# ------------------------------------------------------------------ the clock
def today(db=DB) -> str:
    return clock.info(db)["today"]


def cut_minute(date: str, now: datetime | None = None, db=DB) -> int:
    """Minutes after `date`'s midnight before which orders count: 0 = nothing yet, FULL_DAY = the whole day.

    now=None: the store clock (gondola.now): today is cut at the current minute (the full day once closed); earlier
    days are complete; later days have nothing yet. now given: the business day of `now` (4 a.m. rollover) decides."""
    date = ddate(date)
    if now is None:
        i = clock.info(db)
        if date < i["today"]:
            return FULL_DAY
        if date > i["today"]:
            return 0
        if i["cutoff"] is None:  # closed (or a past data day shown complete)
            return FULL_DAY
        return mins(i["cutoff"])
    biz = (now - timedelta(hours=clock.DAY_CUTOFF_H)).date()
    d = Date.fromisoformat(date)
    if d < biz:
        return FULL_DAY
    if d > biz:
        return 0
    m = int((now - datetime.combine(d, datetime.min.time())).total_seconds() // 60)
    return max(0, min(m, FULL_DAY))


def today_for(now: datetime | None = None, db=DB) -> str:
    """The business date at `now` (store clock if None)."""
    if now is None:
        return clock.info(db)["today"]
    return (now - timedelta(hours=clock.DAY_CUTOFF_H)).date().isoformat()


def today_complete(now: datetime | None = None, db=DB) -> bool:
    t = today_for(now, db)
    return cut_minute(t, now, db) >= clock.close_min(t)


def history_upto(date: str, now: datetime | None = None, db=DB) -> str:
    """First day whose orders a forecast for `date` must not see: `date` itself, or today while it is not over."""
    t = today_for(now, db)
    lim = t if not today_complete(now, db) else ddate(pd.Timestamp(t) + pd.Timedelta(days=1))
    return min(ddate(date), lim)


def now_for(date: str, now: datetime | None = None, db=DB) -> datetime:
    """A datetime for `date` at its cut (for display)."""
    m = cut_minute(date, now, db)
    return datetime.combine(Date.fromisoformat(ddate(date)), datetime.min.time()) + timedelta(minutes=min(m, 24 * 60 - 1))


def store_at(date: str, m: int, db=DB) -> Store:
    """The database as it was `m` minutes after `date`'s midnight (later days hidden)."""
    if m >= 24 * 60:
        return Store(db, cut=(ddate(date), None))
    return Store(db, cut=(ddate(date), hm(max(m, 0))))


# ------------------------------------------------------------------ order counts (whole history, cached)
def _counts(db) -> pd.DataFrame:
    st = Store(db)
    q = """SELECT business_date, channel, CAST(extract(hour FROM created_at)*4 + extract(minute FROM created_at)//15 AS INT) AS bin,
                  COUNT(*) AS n
           FROM orders WHERE status = 'completed' GROUP BY 1, 2, 3"""
    x = st.df(q)
    x["business_date"] = pd.to_datetime(x.business_date)
    return x


def counts(db=DB) -> pd.DataFrame:
    """Completed orders per (business_date, channel, 15-min bin) for the whole history. Callers must filter dates
    themselves (this is the uncut table; use actual_bins for a cut day)."""
    return CACHE.get(("counts", str(db), db_version(db)), lambda: _counts(db))


def actual_bins(date: str, m: int, db=DB) -> pd.DataFrame:
    """Completed orders of `date` created before minute m, per channel and bin (bin, channel, n)."""
    if m <= 0:
        return pd.DataFrame(columns=["bin", "channel", "n"])
    st = store_at(date, m, db)
    q = """SELECT channel, CAST(extract(hour FROM created_at)*4 + extract(minute FROM created_at)//15 AS INT) AS bin, COUNT(*) n
           FROM orders WHERE status='completed' AND business_date = ? GROUP BY 1, 2"""
    return st.df(q, [ddate(date)])


def daily(db=DB, upto: str | None = None) -> pd.DataFrame:
    """The daily frame (uncut, cached); `upto` keeps days strictly before it."""
    df = CACHE.get(("daily", str(db), db_version(db)), lambda: Store(db).daily_frame())
    return df[df.business_date < pd.Timestamp(upto)] if upto else df


# ------------------------------------------------------------------ the day's shape, split by channel
def channel_shape(date: str, sim_dates: list[str], db=DB, cnt: pd.DataFrame | None = None) -> pd.DataFrame:
    """Share of the day's orders per (bin, channel) from the similar days (all strictly before `date`). Rows cover
    every bin from opening to close; shares sum to 1. Overall per-bin share = mean of each day's share; the channel
    mix inside a bin is pooled over the days and smoothed over neighbouring bins."""
    cnt = counts(db) if cnt is None else cnt
    sd = pd.to_datetime([d for d in sim_dates if d < ddate(date)])
    bins = list(range(OPEN_BIN, close_bin(date)))
    x = cnt[cnt.business_date.isin(sd) & cnt.bin.isin(bins)]
    if x.empty:
        sh = pd.DataFrame({"bin": np.repeat(bins, len(CHANNELS)), "channel": CHANNELS * len(bins)})
        sh["share"] = 1.0 / len(sh)
        return sh
    per_day = x.groupby(["business_date", "bin"]).n.sum().unstack(fill_value=0).reindex(columns=bins, fill_value=0)
    per_day = per_day.div(per_day.sum(axis=1), axis=0)
    overall = per_day.reindex(sd, fill_value=0).mean(axis=0)
    overall = overall / overall.sum() if overall.sum() > 0 else overall + 1.0 / len(bins)
    mix = x.groupby(["bin", "channel"]).n.sum().unstack(fill_value=0).reindex(index=bins, columns=CHANNELS, fill_value=0)
    mix = mix.rolling(MIX_SMOOTH_BINS, center=True, min_periods=1).sum()
    tot = mix.sum(axis=1)
    day_mix = mix.sum(axis=0) / max(mix.values.sum(), 1)
    mix = mix.div(tot.where(tot > 0), axis=0).apply(lambda r: r.fillna(day_mix[r.name]))
    sh = (mix.mul(overall, axis=0)).stack().rename("share").reset_index()
    sh.columns = ["bin", "channel", "share"]
    sh["share"] = sh.share / sh.share.sum()
    return sh


# ------------------------------------------------------------------ backtested day errors
def _bt_cache_paths() -> list[Path]:
    return [ROOT / "out" / "backtest_cache.csv", out_dir() / "day_backtests.csv"]


def day_backtests(dates: list[str], db=DB) -> pd.DataFrame:
    """Night-before forecasts re-run for past days (demand.backtest_forecast: trained only on earlier days, with
    the same weather-forecast noise as the close pipeline). Reads the pipeline's cache and Future's own; computes
    and stores what is missing."""
    frames = []
    for p in _bt_cache_paths():
        if p.exists():
            try:
                frames.append(pd.read_csv(p))
            except Exception:  # noqa: BLE001 - a broken cache is just a cache miss
                pass
    have = pd.concat(frames, ignore_index=True).drop_duplicates("date", keep="first") if frames else pd.DataFrame(columns=["date"])
    have["date"] = have.date.astype(str)
    missing = [d for d in dates if d not in set(have.date)]
    if missing:
        st, df = Store(db), daily(db)
        new = [r for r in (demand.backtest_forecast(st, d, df) for d in missing) if r is not None]
        if new:
            mine = out_dir() / "day_backtests.csv"
            old = pd.read_csv(mine) if mine.exists() else pd.DataFrame()
            pd.concat([old, pd.DataFrame(new)], ignore_index=True).drop_duplicates("date", keep="last").to_csv(mine, index=False)
            have = pd.concat([have, pd.DataFrame(new)], ignore_index=True)
    return have[have.date.isin(dates)].sort_values("date").reset_index(drop=True)


def open_days_before(date: str, n: int, db=DB) -> list[str]:
    df = daily(db, upto=date)
    return [ddate(x) for x in df[df.orders > 0].business_date.tail(n)]


def day_errors(date: str, db=DB) -> pd.DataFrame:
    """Backtests of the ERROR_DAYS open days before `date` (the conformal calibration set for `date`)."""
    return CACHE.get(("day_errors", str(db), db_version(db), ddate(date)),
                     lambda: day_backtests(open_days_before(date, ERROR_DAYS, db), db))


# ------------------------------------------------------------------ adjustments (written by the Outlook agent)
def adjustments_path(date: str) -> Path:
    return out_dir() / "outlook" / f"{ddate(date)}.json"


def stored_adjustments(date: str) -> list[dict]:
    p = adjustments_path(date)
    if not p.exists():
        return []
    try:
        return list(json.loads(p.read_text(encoding="utf-8")).get("adjustments") or [])
    except Exception:  # noqa: BLE001
        return []


def adjustment_factor(adjs: list[dict]) -> float:
    """Product of (1 + pct/100), each pct already bounded to +-15; the total is kept within +-30%."""
    f = 1.0
    for a in adjs:
        f *= 1 + max(-15.0, min(15.0, float(a.get("pct") or 0))) / 100
    return max(0.7, min(1.3, f))


def _adj_version(date: str) -> int:
    p = adjustments_path(date)
    return p.stat().st_mtime_ns if p.exists() else 0


# ------------------------------------------------------------------ the morning forecast for a day
def _morning(date: str, db) -> dict:
    st = store_at(date, 0, db)  # nothing of `date` itself
    errs = day_errors(date, db)
    if len(errs) >= 20:
        fc = demand.run_forecast(st, date, errs)
        ratio = (errs.actual / errs.predicted).values
        lo, hi = (float(x) for x in np.quantile(ratio, [0.1, 0.9]))
    else:
        fc = demand.naive_forecast(st, date)
        lo, hi = 0.8, 1.2
    sims = [s["date"] for s in fc["similar_days"]]
    shape = channel_shape(date, sims, db)
    return {"date": date, "p10": fc["p10"], "p50": fc["p50"], "p90": fc["p90"], "lo": lo, "hi": hi,
            "similar_days": fc["similar_days"], "rush": fc["rush"], "model": fc["model"],
            "backtest_mape_60d": fc.get("backtest_mape_60d"), "shape": shape}


def morning(date: str, db=DB, adjusted: bool = True) -> dict:
    """The day forecast as of the night before (cached per date). With adjusted=True the Outlook agent's stored
    bounded adjustments scale it. Adds `bins`: DataFrame(bin, channel, share, p50)."""
    date = ddate(date)
    base = CACHE.get(("morning", str(db), db_version(db), date), lambda: _morning(date, db))
    adjs = stored_adjustments(date) if adjusted else []
    f = adjustment_factor(adjs)
    out = {**base, "adjustments": adjs, "adjustment_factor": round(f, 4),
           "p10": round(base["p10"] * f, 1), "p50": round(base["p50"] * f, 1), "p90": round(base["p90"] * f, 1)}
    b = base["shape"].copy()
    b["p50"] = b.share * out["p50"]
    out["bins"] = b
    return out


def curve_from_bins(bins: pd.DataFrame, col: str = "p50") -> list[dict]:
    """Per-bin totals over channels in the demand.intraday_curve shape: [{bin, time, orders}]."""
    t = bins.groupby("bin")[col].sum()
    return [{"bin": int(k), "time": hm(int(k) * 15), "orders": round(float(v), 3)} for k, v in t.sort_index().items()]


def json_safe(obj):
    """Plain JSON types (numpy / pandas / NaN)."""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return json_safe(obj.to_dict("records"))
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(obj, (pd.Timestamp, datetime, Date)):
        return str(obj)[:19] if isinstance(obj, datetime) else str(obj)[:10]
    return obj
