"""Demand Agent tools: what's coming tomorrow?

Daily total: LightGBM on calendar, weather and event features (Chronos-2 can replace it when available;
the backtest decides which one is used). Intraday: the daily total spread over a 15-minute shape taken from
similar past days. Ranges: split-conformal on the model's own rolling backtest errors.
"""
from __future__ import annotations

import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd

from ..metrics import Store
from .analyst import find_similar_days

warnings.filterwarnings("ignore")
FEATS = ["dow", "rain", "snow", "temp_high_c", "event_lift", "penguins", "steelers", "school_in_session", "dd_promo",
         "holiday_factor", "t", "doy_sin", "doy_cos", "lag_wk_mean", "lag_7"]
PARAMS = dict(n_estimators=300, learning_rate=0.04, num_leaves=15, min_child_samples=8, subsample=0.9,
              subsample_freq=1, colsample_bytree=0.9, verbose=-1, random_state=7)


def features(daily: pd.DataFrame, calendar_extra: pd.DataFrame | None = None) -> pd.DataFrame:
    df = daily.copy()
    if calendar_extra is not None:
        df = pd.concat([df, calendar_extra], ignore_index=True)
    df = df.sort_values("business_date").reset_index(drop=True)
    for c in ("rain", "snow", "school_in_session", "dd_promo"):
        df[c] = df[c].astype(float)
    df["t"] = (df.business_date - df.business_date.min()).dt.days / 365
    doy = df.business_date.dt.dayofyear
    df["doy_sin"], df["doy_cos"] = np.sin(2 * np.pi * doy / 365), np.cos(2 * np.pi * doy / 365)
    s = df.set_index("business_date").orders
    lag7 = s.shift(7, freq="D").reindex(df.business_date).values
    with warnings.catch_warnings():  # the first weeks have no history yet: NaN is expected there
        warnings.simplefilter("ignore", RuntimeWarning)
        wk = np.nanmean(np.vstack([s.shift(7 * k, freq="D").reindex(df.business_date).values for k in (1, 2, 3, 4)]), axis=0)
    df["lag_7"], df["lag_wk_mean"] = lag7, wk
    return df


def _target_row(store: Store, date: str) -> pd.DataFrame:
    cal = store.df("SELECT * FROM calendar WHERE date = ?", [date]).rename(columns={"date": "business_date"})
    ev = store.df("SELECT max(lift) l, max(CASE WHEN event LIKE 'Penguins%' THEN 1 ELSE 0 END) p, "
                  "max(CASE WHEN event LIKE 'Steelers%' THEN 1 ELSE 0 END) s FROM events WHERE date = ?", [date])
    cal["event_lift"] = float(ev.l[0]) if ev.l[0] is not None and not pd.isna(ev.l[0]) else 1.0
    cal["penguins"] = float(ev.p[0]) if ev.p[0] is not None and not pd.isna(ev.p[0]) else 0.0
    cal["steelers"] = float(ev.s[0]) if ev.s[0] is not None and not pd.isna(ev.s[0]) else 0.0
    cal["orders"] = np.nan
    return cal


def _fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """One year can't teach a model what a holiday does (each one appears once), so holidays use a prior
    multiplier from the calendar table and the model learns everything else."""
    tr = train[(train.orders > 0)].dropna(subset=["lag_wk_mean"])
    m = lgb.LGBMRegressor(**PARAMS)
    m.fit(tr[FEATS], np.log(tr.orders / tr.holiday_factor))
    return np.exp(m.predict(test[FEATS])) * test.holiday_factor.values


def naive_same_weekday(df: pd.DataFrame, date: pd.Timestamp) -> float:
    past = df[(df.business_date < date) & (df.dow == date.dayofweek) & (df.orders > 0)].tail(4)
    return float(past.orders.mean())


def backtest_forecast(store: Store, date: str, daily: pd.DataFrame | None = None, weather_noise: float = 0.2,
                      seed: int = 0) -> dict:
    """Re-run the forecast for a past day using only data up to the night before.

    weather_noise: chance the night-before weather forecast got rain wrong (actual weather would flatter the model).
    """
    d = pd.Timestamp(date)
    daily = daily if daily is not None else store.daily_frame()
    f = features(daily)
    test = f[f.business_date == d].copy()
    if test.empty:
        raise ValueError(f"no data for {date}")
    if (f[(f.business_date < d) & (f.orders > 0)].lag_wk_mean.notna()).sum() < 28:
        return None  # not enough history to train
    rng = np.random.default_rng(seed + d.dayofyear)
    if rng.random() < weather_noise:
        test["rain"] = 1.0 - test["rain"]
    pred = float(_fit_predict(f[f.business_date < d], test)[0])
    actual = float(test.orders.iloc[0])
    naive = naive_same_weekday(f, d)
    return {"date": date, "predicted": round(pred, 1), "actual": actual, "error_pct": round((pred - actual) / actual, 4),
            "naive_same_weekday": round(naive, 1), "naive_error_pct": round((naive - actual) / actual, 4)}


def rolling_backtest(store: Store, days: int = 120, end: str | None = None) -> pd.DataFrame:
    daily = store.daily_frame()
    end_d = pd.Timestamp(end) if end else daily.business_date.max()
    dates = daily[(daily.business_date > end_d - pd.Timedelta(days=days)) & (daily.business_date <= end_d) &
                  (daily.orders > 0)].business_date
    rows = [backtest_forecast(store, str(x.date()), daily) for x in dates]
    return pd.DataFrame([r for r in rows if r is not None])


def run_forecast(store: Store, date: str, history_errors: pd.DataFrame | None = None) -> dict:
    """Forecast `date` (normally tomorrow): daily P10/P50/P90, 15-min curve and item demand by daypart."""
    daily = store.daily_frame()
    daily = daily[daily.business_date < pd.Timestamp(date)]  # never let the target day's actuals in
    f = features(daily, _target_row(store, date))
    test = f[f.business_date == pd.Timestamp(date)]
    p50 = float(_fit_predict(f[f.business_date < pd.Timestamp(date)], test)[0])
    if history_errors is None or history_errors.empty:
        history_errors = rolling_backtest(store, days=60)
    ratio = (history_errors.actual / history_errors.predicted).values  # split conformal, multiplicative
    lo, hi = np.quantile(ratio, [0.1, 0.9])
    sims = find_similar_days(store, date, 5, daily)
    curve = intraday_curve(store, [s["date"] for s in sims], p50)
    items = item_demand(store, [s["date"] for s in sims], p50)
    return {"date": date, "p10": round(p50 * lo, 1), "p50": round(p50, 1), "p90": round(p50 * hi, 1),
            "similar_days": sims, "curve": curve, "items": items,
            "rush": rush_window(curve), "model": "lightgbm-daily + similar-day shape",
            "backtest_mape_60d": round(float(np.mean(np.abs(history_errors.error_pct))), 4)}


def naive_forecast(store: Store, date: str) -> dict:
    """Fallback for early history: average of recent same weekdays, with a wide range."""
    daily = store.daily_frame()
    d = pd.Timestamp(date)
    p50 = naive_same_weekday(daily, d)
    if np.isnan(p50):
        p50 = float(daily[daily.orders > 0].orders.tail(7).mean())
    hf = store.df("SELECT holiday_factor FROM calendar WHERE date = ?", [date])
    p50 *= float(hf.holiday_factor[0]) if len(hf) else 1.0  # holiday prior applies here too (closed = 0)
    sims = find_similar_days(store, date, 5, daily)
    curve = intraday_curve(store, [s["date"] for s in sims], p50)
    return {"date": date, "p10": round(p50 * 0.8, 1), "p50": round(p50, 1), "p90": round(p50 * 1.2, 1), "similar_days": sims,
            "curve": curve, "items": item_demand(store, [s["date"] for s in sims], p50), "rush": rush_window(curve),
            "model": "naive same-weekday (not enough history yet)", "backtest_mape_60d": None}


def intraday_curve(store: Store, dates: list[str], total: float) -> list[dict]:
    q = """SELECT business_date, (extract(hour FROM created_at)*4 + extract(minute FROM created_at)//15) AS bin, COUNT(*) n
           FROM orders WHERE business_date IN (SELECT unnest(?::DATE[])) GROUP BY 1,2"""
    x = store.df(q, [dates])
    x["share"] = x.n / x.groupby("business_date").n.transform("sum")
    prof = x.groupby("bin").share.mean()
    prof = prof / prof.sum()
    return [{"bin": int(b), "time": f"{int(b)//4:02d}:{int(b)%4*15:02d}", "orders": round(float(v * total), 2)}
            for b, v in prof.sort_index().items()]


def rush_window(curve: list[dict], frac: float = 0.75) -> dict:
    c = pd.DataFrame(curve)
    dinner = c[c.bin >= 15 * 4]
    peak = dinner.orders.max()
    hot = dinner[dinner.orders >= frac * peak]
    return {"start": hot.time.iloc[0], "end": f"{(hot.bin.iloc[-1] + 1)//4:02d}:{(hot.bin.iloc[-1] + 1)%4*15:02d}",
            "peak_per_15min": round(float(peak), 1)}


def item_demand(store: Store, dates: list[str], total: float) -> list[dict]:
    q = """SELECT o.business_date, l.item,
                  CASE WHEN extract(hour FROM o.created_at) < 15 THEN 'lunch' ELSE 'dinner' END AS daypart, COUNT(*) n
           FROM orders o JOIN order_lines l USING(order_id)
           WHERE o.business_date IN (SELECT unnest(?::DATE[])) GROUP BY 1,2,3"""
    x = store.df(q, [dates])
    per_order = store.df("SELECT business_date, COUNT(*) n FROM orders WHERE business_date IN (SELECT unnest(?::DATE[])) GROUP BY 1",
                         [dates]).set_index("business_date").n
    x["rate"] = x.n / x.business_date.map(per_order)
    r = x.groupby(["item", "daypart"]).rate.mean().reset_index()
    r["units"] = (r.rate * total).round(1)
    return r.drop(columns="rate").to_dict("records")
