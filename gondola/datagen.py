"""Synthetic demo data for Gondola: one year of a delivery-heavy ramen shop.

Fictional store: Hanabi Ramen, Murray Ave, Squirrel Hill, Pittsburgh PA.
History: 2025-11-06 .. 2026-11-05 (the demo close day, a rainy Thursday with a Penguins home game).
The next day (2026-11-06) is generated too, but only into truth/ so forecasts can be scored.

Outputs
  data/raw/    files shaped like what the connectors would receive (POS orders, app payout reports,
               cash drawer shifts, labour, invoices, counts, waste, weather, events)
  data/truth/  ground truth the pipeline never reads (injected anomalies, true inventory, lost sales,
               tomorrow's actual orders). Tests score the agents against it.

Run: python -m gondola.datagen
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
TRUTH = ROOT / "data" / "truth"

SEED = 2026
START = pd.Timestamp("2025-11-06")
CLOSE_DAY = pd.Timestamp("2026-11-05")
TOMORROW = CLOSE_DAY + pd.Timedelta(days=1)
STORE_ID = "hanabi-sqh"

CHANNELS = ["in_store", "doordash", "ubereats", "grubhub"]
BASE_SHARE = np.array([0.34, 0.42, 0.16, 0.08])
COMMISSION = {"doordash": 0.25, "ubereats": 0.27, "grubhub": 0.20}
CARD_FEE = 0.029  # plus $0.30 per card transaction, in-store
APP_MARKUP = 1.10

# name, category, price, uses_chashu (portions), mix weight
MENU = [
    ("Tonkotsu", "ramen", 17.50, 1.0, 0.20),
    ("Shoyu", "ramen", 16.50, 1.0, 0.10),
    ("Spicy Miso", "ramen", 17.50, 1.0, 0.14),
    ("Chicken Paitan", "ramen", 16.50, 0.0, 0.10),
    ("Veggie Miso", "ramen", 15.50, 0.0, 0.07),
    ("Tantanmen", "ramen", 17.00, 0.0, 0.08),
    ("Chashu Don", "rice", 14.00, 1.5, 0.06),
    ("Gyoza", "side", 8.00, 0.0, 0.09),
    ("Karaage", "side", 9.00, 0.0, 0.07),
    ("Chashu Bao", "side", 8.50, 0.5, 0.05),
    ("Edamame", "side", 6.00, 0.0, 0.04),
    ("Takoyaki", "side", 8.50, 0.0, 0.03),
    ("Ramune", "drink", 4.50, 0.0, 0.05),
    ("Iced Green Tea", "drink", 3.50, 0.0, 0.04),
    ("Sapporo", "drink", 7.00, 0.0, 0.03),  # in-store only
    ("Mochi Trio", "dessert", 6.50, 0.0, 0.03),
]
MENU_DF = pd.DataFrame(MENU, columns=["item", "category", "price", "chashu_portions", "weight"])
MENU_DF["item_id"] = [f"m{i:02d}" for i in range(len(MENU_DF))]

# ingredient recipes per menu item: sku -> qty per portion
SKUS = [
    # sku, unit, cost per unit, shelf_life_days, pack_size, supplier
    ("pork_belly", "kg", 7.80, 5, 5, "Strip District Meats"),
    ("chashu", "portion", 0.0, 3, 1, "prepped"),
    ("tonkotsu_broth", "L", 1.10, 4, 1, "prepped"),
    ("chicken_broth", "L", 0.90, 4, 1, "prepped"),
    ("noodles", "portion", 0.55, 4, 40, "Sun Noodle"),
    ("ajitama_egg", "each", 0.42, 4, 30, "Penn Dairy & Eggs"),
    ("chicken_thigh", "kg", 6.20, 4, 5, "Strip District Meats"),
    ("gyoza", "piece", 0.28, 90, 100, "Restaurant Depot"),
    ("bao_bun", "each", 0.35, 60, 50, "Restaurant Depot"),
    ("rice", "kg", 2.10, 365, 20, "Restaurant Depot"),
    ("edamame", "kg", 4.40, 180, 2, "Restaurant Depot"),
    ("takoyaki", "piece", 0.30, 90, 60, "Restaurant Depot"),
    ("ramune", "bottle", 1.20, 365, 24, "Restaurant Depot"),
    ("green_tea", "L", 0.60, 7, 4, "Restaurant Depot"),
    ("sapporo", "bottle", 1.90, 180, 24, "Pittsburgh Beverage"),
    ("mochi", "piece", 0.70, 60, 36, "Restaurant Depot"),
    ("scallion", "kg", 3.10, 7, 1, "Strip District Produce"),
]
SKU_DF = pd.DataFrame(SKUS, columns=["sku", "unit", "unit_cost", "shelf_life_days", "pack_size", "supplier"])

RECIPES = {
    "Tonkotsu": {"chashu": 1, "tonkotsu_broth": 0.45, "noodles": 1, "ajitama_egg": 1, "scallion": 0.01},
    "Shoyu": {"chashu": 1, "chicken_broth": 0.45, "noodles": 1, "ajitama_egg": 1, "scallion": 0.01},
    "Spicy Miso": {"chashu": 1, "tonkotsu_broth": 0.45, "noodles": 1, "ajitama_egg": 0.5, "scallion": 0.01},
    "Chicken Paitan": {"chicken_broth": 0.45, "noodles": 1, "chicken_thigh": 0.09, "ajitama_egg": 1, "scallion": 0.01},
    "Veggie Miso": {"noodles": 1, "scallion": 0.015},
    "Tantanmen": {"tonkotsu_broth": 0.4, "noodles": 1, "scallion": 0.01},
    "Chashu Don": {"chashu": 1.5, "rice": 0.22, "ajitama_egg": 0.5, "scallion": 0.005},
    "Gyoza": {"gyoza": 6},
    "Karaage": {"chicken_thigh": 0.18},
    "Chashu Bao": {"chashu": 0.5, "bao_bun": 2},
    "Edamame": {"edamame": 0.15},
    "Takoyaki": {"takoyaki": 6},
    "Ramune": {"ramune": 1},
    "Iced Green Tea": {"green_tea": 0.4},
    "Sapporo": {"sapporo": 1},
    "Mochi Trio": {"mochi": 3},
}
CHASHU_PER_KG_BELLY = 7.0  # portions from 1 kg pork belly

DOW = np.array([0.86, 0.88, 0.95, 1.00, 1.24, 1.30, 1.05])  # Mon..Sun
OPEN_H, CLOSE_H = 11.0, 22.0
LATE_CLOSE_H = 23.0  # Fri, Sat


# --------------------------------------------------------------------------- context
def build_calendar(rng: np.random.Generator) -> pd.DataFrame:
    days = pd.date_range(START, TOMORROW, freq="D")
    cal = pd.DataFrame({"date": days})
    doy = cal.date.dt.dayofyear.values
    month = cal.date.dt.month.values
    # Pittsburgh-ish weather
    temp = 12 + 13 * np.sin(2 * np.pi * (doy - 110) / 365) + rng.normal(0, 4, len(cal))
    rain_p = np.where(np.isin(month, [4, 5, 6, 7]), 0.42, 0.36)
    precip_day = rng.random(len(cal)) < rain_p
    precip_mm = np.where(precip_day, rng.gamma(1.6, 4.0, len(cal)), 0.0)
    snow = precip_day & (temp < 1.0)
    cal["temp_high_c"] = temp.round(1)
    cal["precip_mm"] = precip_mm.round(1)
    cal["rain"] = precip_day & ~snow
    cal["snow"] = snow
    cal["evening_rain"] = cal.rain & (rng.random(len(cal)) < 0.6)

    # events
    events = []
    # Penguins home games: Oct 8 - Apr 15, about 41, mostly 7pm
    pens_days = [d for d in days if (d.month >= 10 or d.month <= 4) and not (d.month == 4 and d.day > 15)]
    pens = sorted(rng.choice(len(pens_days), size=min(41, len(pens_days)), replace=False))
    for i in pens:
        d = pens_days[i]
        hr = 19.0 if d.dayofweek < 5 else rng.choice([13.0, 15.0, 19.0])
        events.append((d, "Penguins home game", "PPG Paints Arena", hr, 1.08))
    # Steelers home games (Sundays, plus one Thursday night)
    for s in ["2025-11-16", "2025-11-30", "2025-12-14", "2025-12-28", "2026-09-13", "2026-09-27",
              "2026-10-18", "2026-11-01", "2026-11-22"]:
        events.append((pd.Timestamp(s), "Steelers home game", "Acrisure Stadium", 13.0, 1.15))
    events.append((pd.Timestamp("2026-10-08"), "Steelers home game (TNF)", "Acrisure Stadium", 20.25, 1.14))
    # Pirates home games Apr-Sep (small effect)
    pir_days = [d for d in days if 4 <= d.month <= 9]
    for i in sorted(rng.choice(len(pir_days), size=81, replace=False)):
        events.append((pir_days[i], "Pirates home game", "PNC Park", 19.1, 1.02))
    events.append((pd.Timestamp("2026-02-08"), "Super Bowl Sunday", "TV", 18.5, 1.35))
    ev = pd.DataFrame(events, columns=["date", "event", "venue", "start_hour", "lift"])
    # forced demo context
    ev = ev[~((ev.date == CLOSE_DAY) & ev.event.str.startswith("Penguins"))]
    ev = pd.concat([ev, pd.DataFrame([(CLOSE_DAY, "Penguins home game", "PPG Paints Arena", 19.0, 1.08)],
                                     columns=ev.columns)], ignore_index=True)
    ev = ev[ev.date <= TOMORROW].sort_values("date").reset_index(drop=True)

    cal.loc[cal.date == CLOSE_DAY, ["rain", "snow", "evening_rain", "precip_mm", "temp_high_c"]] = [True, False, True, 9.4, 8.2]
    cal.loc[cal.date == TOMORROW, ["rain", "snow", "evening_rain", "precip_mm", "temp_high_c"]] = [False, False, False, 0.0, 10.5]

    holidays = {
        "2025-11-27": ("Thanksgiving", 0.35), "2025-11-28": ("Black Friday", 1.10),
        "2025-12-24": ("Christmas Eve", 0.70), "2025-12-25": ("Christmas (closed)", 0.0),
        "2025-12-31": ("New Year's Eve", 0.85), "2026-01-01": ("New Year's Day", 0.80),
        "2026-02-14": ("Valentine's Day", 1.10), "2026-05-25": ("Memorial Day", 0.85),
        "2026-07-04": ("Independence Day", 0.70), "2026-09-07": ("Labor Day", 0.85),
    }
    cal["holiday"] = cal.date.dt.strftime("%Y-%m-%d").map(lambda s: holidays.get(s, (None, 1.0))[0])
    cal["holiday_factor"] = cal.date.dt.strftime("%Y-%m-%d").map(lambda s: holidays.get(s, (None, 1.0))[1])
    # CMU / Pitt in session (Squirrel Hill student demand)
    def in_session(d):
        if (d.month == 12 and d.day >= 19) or (d.month == 1 and d.day < 12):
            return False
        if (d.month == 3 and 7 <= d.day <= 15):
            return False
        if (d.month == 5 and d.day >= 10) or d.month in (6, 7) or (d.month == 8 and d.day < 24):
            return False
        return True
    cal["school_in_session"] = cal.date.map(in_session)
    # DoorDash promo days (merchant-funded, run by the store)
    promo = rng.random(len(cal)) < 0.07
    cal["dd_promo"] = promo
    cal.loc[cal.date.isin([CLOSE_DAY, TOMORROW]), "dd_promo"] = False
    cal["dow"] = cal.date.dt.dayofweek
    return cal, ev


# --------------------------------------------------------------------------- demand
def day_orders_expected(row, ev_day: pd.DataFrame, t_years: float) -> float:
    base = 430.0 * DOW[row.dow]
    season = 1 + 0.12 * np.cos(2 * np.pi * (row.date.dayofyear - 20) / 365)  # ramen: winter up
    weather = (1.12 if row.rain else 1.0) * (1.18 if row.snow else 1.0) * (1.04 if row.temp_high_c < 3 else 1.0)
    event = float(np.prod(ev_day.lift.values)) if len(ev_day) else 1.0
    school = 1.0 if row.school_in_session else 0.87
    promo = 1.09 if row.dd_promo else 1.0
    trend = 1 + 0.08 * t_years
    return base * season * weather * event * school * promo * trend * row.holiday_factor


def intraday_times(rng, n, dow, ev_day, rainy_evening) -> np.ndarray:
    close_h = LATE_CLOSE_H if dow in (4, 5) else CLOSE_H
    comps = [(12.25, 0.7, 0.36), (18.6, 1.05, 0.56), (21.2, 0.5, 0.08 if close_h == CLOSE_H else 0.12)]
    if dow >= 5:
        comps[0] = (12.9, 0.95, 0.40)
    w = np.array([c[2] for c in comps]); w = w / w.sum()
    k = rng.choice(len(comps), size=n, p=w)
    mu = np.array([c[0] for c in comps])[k]
    sd = np.array([c[1] for c in comps])[k]
    t = rng.normal(mu, sd)
    for _, e in ev_day.iterrows():  # game-time delivery bump
        if e.start_hour >= 17 and e.event != "Pirates home game":
            m = rng.random(n) < 0.10
            t[m] = rng.normal(e.start_hour + 0.6, 0.55, m.sum())
    if rainy_evening:
        m = rng.random(n) < 0.06
        t[m] = rng.normal(19.2, 0.6, m.sum())
    t = np.clip(t, OPEN_H + 0.02, close_h - 0.05)
    return np.sort(t)


def main() -> None:
    rng = np.random.default_rng(SEED)
    RAW.mkdir(parents=True, exist_ok=True)
    TRUTH.mkdir(parents=True, exist_ok=True)
    cal, ev = build_calendar(rng)

    item_names = MENU_DF.item.values
    prices = MENU_DF.price.values
    chashu_use = MENU_DF.chashu_portions.values
    w_all = MENU_DF.weight.values / MENU_DF.weight.sum()
    w_app = w_all.copy(); w_app[item_names == "Sapporo"] = 0; w_app = w_app / w_app.sum()
    chashu_items = set(item_names[chashu_use > 0])
    CAT = dict(zip(MENU_DF.item, MENU_DF.category))
    CH_USE = dict(zip(MENU_DF.item, MENU_DF.chashu_portions))
    PRICE = dict(zip(MENU_DF.item, MENU_DF.price))

    orders, lines, anomalies, lost, chashu_log = [], [], [], [], []
    payout_rows = {"doordash": [], "ubereats": [], "grubhub": []}
    cash_shifts, labour, sold_out_events = [], [], []
    order_seq = 0
    chashu_hist = []  # usage history for the manager's par rule
    commission_bad_days = set(pd.to_datetime(["2026-01-17", "2026-03-06", "2026-05-22", "2026-07-10", "2026-09-18"]))

    for _, row in cal.iterrows():
        d = row.date
        is_tomorrow = d == TOMORROW
        if row.holiday_factor == 0:
            chashu_hist.append((d, 0.0, False))
            continue
        ev_day = ev[ev.date == d]
        t_years = (d - START).days / 365
        lam = day_orders_expected(row, ev_day, t_years)
        n = int(rng.poisson(lam * np.exp(rng.normal(0, 0.06))))
        if d == CLOSE_DAY:
            n = 489
        times = intraday_times(rng, n, row.dow, ev_day, row.evening_rain)

        share = BASE_SHARE.copy()
        if row.rain or row.snow:
            share = share + np.array([-0.07, 0.04, 0.02, 0.01])
        if len(ev_day[ev_day.event.str.contains("Penguins|Steelers|Super")]):
            share = share + np.array([-0.03, 0.02, 0.01, 0.0])
        share = share / share.sum()
        chans = rng.choice(CHANNELS, size=n, p=share)

        # manager's chashu par rule: avg of last 4 same weekdays * 1.05, rounded up to batch of 10
        same = [(u, so) for (dd, u, so) in chashu_hist if dd.dayofweek == d.dayofweek and u > 0][-4:]
        bump = 1.15 if any(so for _, so in same[-2:]) else 1.0
        par = int(np.ceil((np.mean([u for u, _ in same]) * 1.10 * bump if same else 280) / 10) * 10)
        if d == CLOSE_DAY:
            par = 0  # set below so that chashu runs out at 8:40 pm
        on_hand_chashu = float(par)
        soldout_at = None
        app_live_until = None
        used_chashu = 0.0

        day_start = len(orders)
        # pre-draw basket for each order
        baskets = []
        for i in range(n):
            ch = chans[i]
            k = 1 + rng.poisson(1.15)
            w = w_all if ch == "in_store" else w_app
            items = list(rng.choice(item_names, size=k, p=w))
            if not any(CAT[it] in ("ramen", "rice") for it in items) and rng.random() < 0.7:
                items.append(rng.choice(item_names[:7], p=w_all[:7] / w_all[:7].sum()))
            baskets.append(items)
        if d == CLOSE_DAY:
            # choose par so the cumulative chashu use crosses par at 20:40
            cum = 0.0
            for i in range(n):
                if times[i] >= 20 + 40 / 60:
                    break
                cum += sum(CH_USE[it] for it in baskets[i])
            par = int(np.floor(cum))
            on_hand_chashu = float(par)
        lag_min = 41 if d == CLOSE_DAY else int(np.clip(rng.gamma(2.2, 14), 8, 75))

        for i in range(n):
            t = times[i]
            ch = chans[i]
            items = baskets[i]
            need = sum(CH_USE[it] for it in items)
            status, reason = "completed", None
            if soldout_at is None and need > 0 and on_hand_chashu - need < 0:
                soldout_at = t
                app_live_until = t + lag_min / 60
                sold_out_events.append({"business_date": d, "item_group": "chashu", "sold_out_at_h": round(t, 3),
                                        "apps_live_minutes": lag_min, "par": par})
            if soldout_at is not None and need > 0:
                if ch == "in_store" or t > app_live_until:
                    # customer picks something else or leaves (lost sale)
                    lost.append({"business_date": d, "channel": ch, "time_h": t, "items": "|".join(items)})
                    items = [it for it in items if it not in chashu_items]
                    if not items:
                        continue
                    need = 0
                else:
                    status, reason = "cancelled", "item_unavailable"
            if status == "completed":
                on_hand_chashu -= need
                used_chashu += need
            order_seq += 1
            oid = f"o{order_seq:07d}"
            p = np.array([PRICE[it] for it in items])
            if ch != "in_store":
                p = np.round(p * APP_MARKUP, 2)
            sub = float(p.sum())
            if status == "completed" and rng.random() < 0.003:
                status, reason = "cancelled", rng.choice(["customer_cancelled", "dasher_unavailable"])
            ts = d + pd.Timedelta(hours=float(t))
            tender = None
            if ch == "in_store":
                tender = "cash" if rng.random() < 0.28 else "card"
            tip = 0.0 if ch != "in_store" else (round(sub * rng.choice([0, 0.15, 0.18, 0.2]), 2) if tender == "card" else 0.0)
            promo = bool(row.dd_promo and ch == "doordash" and rng.random() < 0.45)
            orders.append({"order_id": oid, "business_date": d, "created_at": ts, "channel": ch,
                           "subtotal": round(sub, 2), "tax": round(sub * 0.07, 2) if ch == "in_store" else 0.0,
                           "tip": tip, "tender": tender, "status": status, "cancel_reason": reason, "promo": promo})
            for it, pr in zip(items, p):
                lines.append({"order_id": oid, "item": it, "price": float(pr)})

            # app payout lines (reported by the platform)
            if ch != "in_store":
                rate = COMMISSION[ch]
                if ch == "doordash" and d in commission_bad_days:
                    rate = 0.30
                commission = round(sub * rate, 2) if status == "completed" else 0.0
                marketing = 2.00 if promo and status == "completed" else 0.0
                err = 0.0
                err_type = None
                if status == "completed":
                    r = rng.random()
                    if r < 0.008:
                        err_type = "legit"
                        err = float(rng.choice(p))
                    elif r < 0.011:
                        err_type = "legit_partial"  # e.g. wrong side / missing sauce: part of an item, valid
                        err = round(float(rng.choice(p)) * float(rng.choice([0.25, 0.5])), 2)
                    elif r < 0.017:
                        err_type = rng.choice(["over_refund", "item_not_on_order"]) if len(items) > 1 else "item_not_on_order"
                        if err_type == "over_refund":
                            err = round(min(sub, float(rng.choice(p)) + rng.uniform(6, 14)), 2)
                        else:
                            notin = [x for x in item_names if x not in items and x != "Sapporo"]
                            err = round(float(prices[item_names == rng.choice(notin)][0]) * APP_MARKUP, 2)
                cancel_payout = 0.0
                if status == "cancelled" and reason == "item_unavailable":
                    cancel_payout = 0.0  # merchant-caused cancellation: no payout
                net = (sub - commission - marketing - err) if status == "completed" else cancel_payout
                rec = {"order_id": oid, "business_date": d, "subtotal": round(sub, 2) if status == "completed" else 0.0,
                       "commission": commission, "marketing_fee": marketing, "error_charge": round(err, 2),
                       "adjustment": 0.0, "net_payout": round(net, 2), "status": status}
                drop = status == "completed" and rng.random() < 0.0025
                if d >= CLOSE_DAY - pd.Timedelta(days=1):
                    drop = False
                if drop:
                    anomalies.append({"business_date": d, "type": "missing_from_payout", "channel": ch,
                                      "order_id": oid, "amount": round(sub - commission - marketing, 2)})
                else:
                    payout_rows[ch].append(rec)
                if err_type in ("over_refund", "item_not_on_order"):
                    anomalies.append({"business_date": d, "type": f"error_charge_{err_type}", "channel": ch,
                                      "order_id": oid, "amount": round(err, 2)})
                if ch == "doordash" and d in commission_bad_days and status == "completed":
                    anomalies.append({"business_date": d, "type": "commission_overcharge", "channel": ch,
                                      "order_id": oid, "amount": round(sub * (0.30 - 0.25), 2)})

        chashu_hist.append((d, used_chashu, soldout_at is not None))
        chashu_log.append({"business_date": d, "par": par, "used": round(used_chashu, 1),
                           "sold_out": soldout_at is not None})
        if is_tomorrow:
            continue

        # cash drawer shift
        day_orders = orders[day_start:]
        cash_sales = sum(o["subtotal"] + o["tax"] for o in day_orders if o["tender"] == "cash" and o["status"] == "completed")
        opening = 200.0
        paid_out = float(rng.choice([0, 0, 0, 18.5, 32.0]))
        expected = round(opening + cash_sales - paid_out, 2)
        noise = float(np.round(rng.normal(0, 2.0) * 4) / 4)
        counted = round(expected + noise, 2)
        cash_shifts.append({"shift_id": f"cds-{d:%Y%m%d}", "business_date": d, "state": "CLOSED",
                            "opened_at": d + pd.Timedelta(hours=10.5),
                            "ended_at": d + pd.Timedelta(hours=(LATE_CLOSE_H if row.dow in (4, 5) else CLOSE_H) + 0.4),
                            "opening_cash": opening, "cash_payments": round(cash_sales, 2), "paid_out": paid_out,
                            "expected_cash": expected, "closed_cash": counted})

        # labour (hours by role)
        vol = n / 430
        cook_h = 92 * vol ** 0.6 + rng.normal(0, 5)
        front_h = 70 * vol ** 0.5 + rng.normal(0, 5)
        dish_h = 24 * vol ** 0.4 + rng.normal(0, 2)
        if rng.random() < 0.04:  # over-scheduled day
            front_h += 14
            anomalies.append({"business_date": d, "type": "labour_overscheduled", "channel": "store",
                              "order_id": None, "amount": 14 * 16.0})
        for role, h, wage in (("cook", cook_h, 19.0), ("front", front_h, 15.5), ("dish", dish_h, 15.0), ("manager", 13, 26.0)):
            labour.append({"business_date": d, "role": role, "hours": round(max(h, 4), 2), "wage": wage})

    # forced DoorDash error charges on the day before close: three disputable charges totalling $86.40.
    # DoorDash reporting data for day D arrives on D+1 evening, so the demo close (Thu) verifies Wednesday.
    VERIFY_DAY = CLOSE_DAY - pd.Timedelta(days=1)
    dd_close = [r for r in payout_rows["doordash"] if r["business_date"] == VERIFY_DAY and r["status"] == "completed"]
    for r in dd_close:
        if r["error_charge"] > 0:  # clear any random ones on the demo day
            r["net_payout"] = round(r["net_payout"] + r["error_charge"], 2); r["error_charge"] = 0.0
    anomalies = [a for a in anomalies if not (a["business_date"] == VERIFY_DAY and a["type"].startswith("error_charge"))]
    big = [k for k, r in enumerate(dd_close) if r["subtotal"] >= 40]
    picks = rng.choice(big, size=3, replace=False)
    for amt, k, typ in zip([31.20, 28.60, 26.60], picks, ["over_refund", "over_refund", "item_not_on_order"]):
        r = dd_close[k]
        r["error_charge"] = amt; r["net_payout"] = round(r["net_payout"] - amt, 2)
        anomalies.append({"business_date": VERIFY_DAY, "type": f"error_charge_{typ}", "channel": "doordash",
                          "order_id": r["order_id"], "amount": amt})

    # injected cash shortages (+ the demo day)
    cs = pd.DataFrame(cash_shifts)
    short_days = rng.choice(cs.index[cs.business_date < CLOSE_DAY], size=10, replace=False)
    for i in short_days:
        amt = float(np.round(rng.uniform(20, 60) * 4) / 4)
        cs.loc[i, "closed_cash"] = round(cs.loc[i, "expected_cash"] - amt, 2)
        anomalies.append({"business_date": cs.loc[i, "business_date"], "type": "cash_short", "channel": "store",
                          "order_id": None, "amount": amt})
    i = cs.index[cs.business_date == CLOSE_DAY][0]
    cs.loc[i, "closed_cash"] = round(cs.loc[i, "expected_cash"] - 23.50, 2)
    anomalies.append({"business_date": CLOSE_DAY, "type": "cash_short", "channel": "store", "order_id": None, "amount": 23.50})

    od = pd.DataFrame(orders)
    ol = pd.DataFrame(lines)
    hist = od[od.business_date <= CLOSE_DAY]
    hist_lines = ol[ol.order_id.isin(hist.order_id)]
    tomorrow_orders = od[od.business_date == TOMORROW]

    # ---------------------------------------------------------------- inventory: invoices, waste, counts
    inv_rows, waste_rows, count_rows, truth_inv = [], [], [], []
    comp = hist[hist.status == "completed"][["order_id", "business_date"]].merge(hist_lines, on="order_id")
    usage = []
    for it, rec in RECIPES.items():
        sub = comp[comp.item == it].groupby("business_date").size()
        for sku, q in rec.items():
            usage.append(pd.DataFrame({"business_date": sub.index, "sku": sku, "theoretical": sub.values * q}))
    usage = pd.concat(usage).groupby(["business_date", "sku"], as_index=False).theoretical.sum()
    days = pd.date_range(START, CLOSE_DAY)
    tracked = [s for s in SKU_DF.sku if s not in ("chashu", "tonkotsu_broth", "chicken_broth")]
    tracked.append("pork_belly")
    tracked = sorted(set(tracked))
    on_hand = {}
    avg_use = usage.groupby("sku").theoretical.mean().to_dict()
    # pork belly is consumed through chashu prep
    cl = pd.DataFrame(chashu_log)
    for s in tracked:
        on_hand[s] = (avg_use.get(s, 1.0) if s != "pork_belly" else cl.par.mean() / CHASHU_PER_KG_BELLY) * 4
    pack = SKU_DF.set_index("sku").pack_size.to_dict()
    cost = SKU_DF.set_index("sku").unit_cost.to_dict()
    supplier = SKU_DF.set_index("sku").supplier.to_dict()
    inv_id = 0
    for d in days:
        u = usage[usage.business_date == d].set_index("sku").theoretical.to_dict()
        par_today = cl.loc[cl.business_date == d, "par"]
        u["pork_belly"] = float(par_today.iloc[0]) / CHASHU_PER_KG_BELLY if len(par_today) else 0.0
        # deliveries Mon/Wed/Fri: order up to 4 days of average use
        if d.dayofweek in (0, 2, 4):
            inv_id += 1
            for s in tracked:
                target = (avg_use.get(s, 0.0) if s != "pork_belly" else cl.par.mean() / CHASHU_PER_KG_BELLY) * 4.2
                need = target - on_hand[s]
                if need > 0:
                    packs = int(np.ceil(need / pack[s]))
                    qty = packs * pack[s]
                    price = cost[s] * (1 + (0.18 if (s == "pork_belly" and d >= pd.Timestamp("2026-09-01")) else 0.0))
                    price *= np.exp(rng.normal(0, 0.02))
                    inv_rows.append({"invoice_id": f"inv{inv_id:05d}", "supplier": supplier[s], "received_at": d + pd.Timedelta(hours=9.5),
                                     "business_date": d, "sku": s, "qty": qty, "unit_cost": round(price, 3)})
                    on_hand[s] += qty
        for s in tracked:
            th = u.get(s, 0.0)
            actual = th
            if s == "noodles" and d.dayofweek == 4:
                actual *= 1.12  # Friday over-portioning (hidden)
            if s == "sapporo" and pd.Timestamp("2026-03-02") <= d <= pd.Timestamp("2026-03-22"):
                actual += 6  # shrink (hidden)
            w = 0.0
            if rng.random() < 0.15 and SKU_DF.set_index("sku").shelf_life_days[s] <= 7:
                w = round(th * rng.uniform(0.02, 0.06), 3)
                waste_rows.append({"business_date": d, "sku": s, "qty": w, "reason": rng.choice(["expired", "dropped", "overcooked"])})
            on_hand[s] = max(on_hand[s] - actual - w, 0)
            truth_inv.append({"business_date": d, "sku": s, "theoretical_use": round(th, 3), "actual_use": round(actual, 3),
                              "waste": w, "on_hand_true": round(on_hand[s], 3)})
        if d.dayofweek == 6 or d == CLOSE_DAY:  # weekly count Sunday night (+ demo day)
            for s in tracked:
                noisy = on_hand[s] * np.exp(rng.normal(0, 0.03))
                count_rows.append({"business_date": d, "sku": s, "counted_qty": round(noisy, 2),
                                   "method": "video" if rng.random() < 0.5 else "manual"})
    anomalies.append({"business_date": pd.Timestamp("2026-03-02"), "type": "shrink_sapporo", "channel": "store",
                      "order_id": None, "amount": 6 * 21 * 7.0})
    for d in days[days.dayofweek == 4]:
        anomalies.append({"business_date": d, "type": "overportion_noodles", "channel": "store", "order_id": None, "amount": None})

    # ---------------------------------------------------------------- write raw (connector-shaped)
    pos = hist.copy()
    pos["created_at"] = pos.created_at.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    pos["business_date"] = pos.business_date.dt.strftime("%Y-%m-%d")
    pos.to_csv(RAW / "pos_orders.csv", index=False)
    hist_lines.to_csv(RAW / "pos_order_lines.csv", index=False)
    for ch, rows in payout_rows.items():
        p = pd.DataFrame(rows)
        p = p[pd.to_datetime(p.business_date) <= CLOSE_DAY].copy()
        p["business_date"] = pd.to_datetime(p.business_date).dt.strftime("%Y-%m-%d")
        if ch == "doordash":  # Report Builder-like column names
            p = p.rename(columns={"order_id": "DoorDash order ID (POS ref)", "business_date": "Timestamp local date",
                                  "subtotal": "Subtotal", "commission": "Commission", "marketing_fee": "Marketing fees",
                                  "error_charge": "Error charges", "adjustment": "Adjustments", "net_payout": "Net total",
                                  "status": "Final order status"})
        lag = {"doordash": pd.Timedelta(hours=22 + 24), "ubereats": pd.Timedelta(days=3, hours=12),
               "grubhub": pd.Timedelta(days=2, hours=12)}[ch]  # D+1 ~10pm ET; Uber up to 72h
        p["available_at"] = (pd.to_datetime(p[[c for c in p.columns if "date" in c.lower()][0]]) + lag).dt.strftime("%Y-%m-%dT%H:%M:%S")
        p.to_csv(RAW / f"{ch}_payout_report.csv", index=False)
    cs2 = cs.copy()
    for c in ("business_date", "opened_at", "ended_at"):
        cs2[c] = cs2[c].astype(str)
    (RAW / "cash_drawer_shifts.json").write_text(json.dumps({"cash_drawer_shifts": cs2.to_dict("records")}, indent=1), encoding="utf-8")
    pd.DataFrame(labour).to_csv(RAW / "labour_shifts.csv", index=False)
    pd.DataFrame(inv_rows).to_csv(RAW / "invoices.csv", index=False)
    pd.DataFrame(waste_rows).to_csv(RAW / "waste_log.csv", index=False)
    pd.DataFrame(count_rows).to_csv(RAW / "counts.csv", index=False)
    cal.drop(columns=["holiday_factor"]).to_csv(RAW / "weather_calendar.csv", index=False)  # includes tomorrow's weather forecast row
    cal[["date", "holiday", "holiday_factor"]].to_csv(TRUTH / "holiday_effects.csv", index=False)
    ev.to_csv(RAW / "events.csv", index=False)
    MENU_DF.to_csv(RAW / "menu.csv", index=False)
    SKU_DF.to_csv(RAW / "skus.csv", index=False)
    pd.DataFrame([{"item": it, "sku": s, "qty": q} for it, r in RECIPES.items() for s, q in r.items()]).to_csv(RAW / "recipes.csv", index=False)
    cl[cl.business_date <= CLOSE_DAY].to_csv(RAW / "prep_log.csv", index=False)  # chashu prepped per day (par) and usage

    # ---------------------------------------------------------------- truth
    an = pd.DataFrame(anomalies)
    an.to_csv(TRUTH / "anomalies.csv", index=False)
    pd.DataFrame(truth_inv).to_csv(TRUTH / "inventory_truth.csv", index=False)
    pd.DataFrame(lost).to_csv(TRUTH / "lost_sales.csv", index=False)
    pd.DataFrame(sold_out_events).to_csv(TRUTH / "sold_out_events.csv", index=False)
    tomorrow_orders.to_csv(TRUTH / "tomorrow_orders.csv", index=False)
    ol[ol.order_id.isin(tomorrow_orders.order_id)].to_csv(TRUTH / "tomorrow_order_lines.csv", index=False)

    print(f"orders {len(hist):,}  lines {len(hist_lines):,}  days {hist.business_date.nunique()}  "
          f"anomalies {len(an):,}  sold-out days {len(sold_out_events)}  tomorrow orders {len(tomorrow_orders)}")


if __name__ == "__main__":
    main()
